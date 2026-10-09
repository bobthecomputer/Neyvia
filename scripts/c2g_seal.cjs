'use strict';
// Seal completed evidence. This never runs tasks or repairs returned answers.
const fs=require('node:fs'),crypto=require('node:crypto'),path=require('node:path');
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''));
const reference=p=>({path:p,sha256:hash(fs.readFileSync(p)),bytes:fs.statSync(p).size});
const requireThat=(yes,message)=>{if(!yes)throw Error(message);};
const output='scripts/evidence/C2g.json',runPath='scripts/evidence/C2g-frozen36-final.json',gradesPath='scripts/evidence/C2g-grades-final.json';
requireThat(!fs.existsSync(output),'Preserve the existing seal');
const run=read(runPath),grades=read(gradesPath);
requireThat(run.finishedAt&&run.tasks.length===36&&run.sourcesUnchanged===true,'Complete unchanged-source frozen36 run required');
requireThat(grades.run.sha256===reference(runPath).sha256&&!grades.draft&&grades.summary.ungraded===0,'Final independent grade must bind exact completed run');
const changed=Object.entries(run.sourcesAtFinish).filter(([p,sha])=>reference(p).sha256!==sha);
requireThat(!changed.length,'Execution sources changed after the final panel');
let observations=0;for(const task of run.tasks)for(const ref of task.observations){requireThat(reference(ref.path).sha256===ref.sha256,'Observation changed: '+ref.path);observations++;}
const guardPath='scripts/evidence/C2g-native-closed-completion.json',guard=read(guardPath),cleanup=read('scripts/evidence/C2g-cleanup.json');
requireThat(guard.closed===true&&guard.guard.closed===true&&guard.guard.ok===true,'Closed private-desktop guard required');
requireThat(cleanup.assignedPortsListening.length===0&&cleanup.ownedSessionsReturned===true,'Owned runtime cleanup has not completed');
const requiredProofs={
 registeredCascade:'scripts/evidence/C2g-task-proof-completion.json',
 obscuraAbilities:'scripts/evidence/C2g-browser-fragment-abilities.json',
 nativeAbilities:'scripts/evidence/C2g-native-abilities-integrated.json',
 typedPreferences:'scripts/evidence/C2g-typed-preferences-final-engine.json',
 ports:'scripts/evidence/C2g-browser-port-contract.json',
 fragmentPixels:'scripts/evidence/C2g-scroll-background-after.json',
 manual:'scripts/evidence/C2g-manual-contract.json',
 nativeBuild:'scripts/evidence/C2g-native-refusal-build.json',
 engineAdmission:'scripts/evidence/C2g-engine-fragment-admission.json',
 syntax:'scripts/evidence/C2g-source-checks-completion.json'};
const proofs=Object.fromEntries(Object.entries(requiredProofs).map(([name,p])=>{
 const value=read(p);if(Array.isArray(value.checks))requireThat(value.checks.length&&value.checks.every(row=>row.ok===true||row.passed===true||row.exitCode===0),'Proof failed: '+p);
 if(name==='registeredCascade'||name==='manual')requireThat(value.ok===true,'Proof incomplete: '+p);
 if(name==='syntax')requireThat(value.diffCheckExitCode===0,'Source whitespace check failed');
 if(name==='nativeBuild')requireThat(value.exitCode===0&&value.sourcesUnchanged===true,'Native build invalid');
 return [name,{...reference(p),checks:value.checks?.length??null}];
}));
const nativeBuild=read(requiredProofs.nativeBuild),admission=read(requiredProofs.engineAdmission);
requireThat(reference(nativeBuild.exe).sha256===nativeBuild.sha256,'Admitted native executable changed');
const modelReceipts=run.tasks.flatMap(t=>t.modelReceipts||[]);
const knownTokens=modelReceipts.reduce((total,r)=>total+(r.usage?.input_tokens||0)+(r.usage?.output_tokens||0),0);
const failedProviderAttempts=modelReceipts.flatMap(r=>r.attempts||[r]).filter(r=>r.code!==0).length;
const unknownUsageAttempts=modelReceipts.flatMap(r=>r.attempts||[r]).filter(r=>!r.usage).length;
const needsOwner=grades.grades.filter(g=>g.outcome==='needs_owner');
// The requested exception is specifically a confirmed CAPTCHA, not any wall.
const confirmedCaptcha=needsOwner.filter(g=>/captcha/i.test(JSON.stringify(g.ownerBoundary))&&!/confirmedCaptcha["\s:]+false/.test(JSON.stringify(g.ownerBoundary)));
const attemptMedian=grades.metrics.deterministicTaskLatencyP50Ms,goalMedian=grades.metrics.endToEndGoalLatencyP50Ms;
const target={minimumPasses:34,medianLimitMs:30000,passed:grades.summary.passed>=34,
 onlyConfirmedCaptchaLeft:grades.summary.failed===0&&needsOwner.length===confirmedCaptcha.length,
 attemptMedianUnder30s:attemptMedian<30000,successfulGoalMedianUnder30s:goalMedian!==null&&goalMedian<30000};
target.met=target.passed&&target.onlyConfirmedCaptchaLeft&&target.attemptMedianUnder30s&&target.successfulGoalMedianUnder30s;
const evidence=fs.readdirSync('scripts/evidence',{recursive:true}).filter(p=>p.startsWith('C2g-')&&!fs.statSync(path.join('scripts/evidence',p)).isDirectory()).map(p=>reference('scripts/evidence/'+p.replace(/\\/g,'/')));
const previous=[['original','scripts/evidence/C2g-frozen36.json','scripts/evidence/C2g-grades.json'],['repaired','scripts/evidence/C2g-frozen36-repaired.json','scripts/evidence/C2g-grades-repaired.json']].map(([name,r,g])=>({name,run:reference(r),grades:reference(g),summary:read(g).summary,metrics:read(g).metrics}));
const seal={schema:'neyvia.C2g.completion@1',sealedAt:new Date().toISOString(),branch:'track/c2-browser',baseCommit:'6a21b427',
 boundary:'Local source and task-local runtime evidence. No push, merge, NAS sync or public promotion. A working cascade and feature proof do not establish the requested frozen36 success target.',
 run:reference(runPath),independentGrades:reference(gradesPath),taskSet:grades.taskSet,sources:run.sourcesAtFinish,
 observationDigestsVerified:observations,previousAttempts:previous,summary:grades.summary,
 metrics:{passed:grades.summary.passed,failed:grades.summary.failed,needsOwner:grades.summary.needs_owner,
  confirmedCaptchaExceptions:confirmedCaptcha.length,taskLatencyP50Ms:attemptMedian,taskLatencyP95Ms:grades.metrics.deterministicTaskLatencyP95Ms,
  successfulGoalLatencyP50Ms:goalMedian,successfulGoalLatencyP95Ms:grades.metrics.endToEndGoalLatencyP95Ms,
  successOverAll:grades.summary.passed/36,planningCalls:modelReceipts.length,providerAttempts:modelReceipts.reduce((n,r)=>n+(r.providerAttempts||1),0),
  failedProviderAttempts,knownProviderTokens:knownTokens,unknownUsageAttempts,providerCostUSD:null,
  costBoundary:'Actual planner receipts only. Dollars, engineering/reviewer tokens, CPU, electricity and operator time are unmetered. Missing usage is unknown, never zero.'},target,
 mechanism:{registeredTool:'neyvia.browser.task.run',sequence:['goal-checked compiled replay','frozen CPU LAYA within calibrated scope','actual gpt-6-luna typed planner'],
  ordinaryEngineRetry:'At most one ordinary WebView2 recovery for observed JavaScript/rendering/navigation failure; private C1 desktop, advertised automation, polite 1500ms delay. CAPTCHA, login and human-verification walls stop.',
  proofLimit:'Exact fresh quote and goal predicate gates are mechanisms, not an independent semantic judgment; final every-clause grading supplies that judgment.',
  actionLimit:'Uncertain dispatched effects stop. Only explicit pre-dispatch stale/navigation refusals permit bounded refresh and replan. Compiled stored targets exclude transient element IDs.'},
 proofs,native:{...reference(nativeBuild.exe),build:proofs.nativeBuild,guard:reference(guardPath),launch:reference('scripts/evidence/C2g-native-launch-completion.json')},
 engine:{admission:proofs.engineAdmission,engineSha256:read(requiredProofs.obscuraAbilities).engineSha256,sourceHashes:admission.sourceHashes},
 failures:grades.grades.filter(g=>g.outcome!=='passed').map(g=>({id:g.id,outcome:g.outcome,reason:g.reason,missingClauses:g.missingClauses,ownerBoundary:g.ownerBoundary,evidence:g.ownerBoundaryEvidence})),
 limitations:['One correlated warm frozen panel, not a matched cold/unseen-site comparison or general-browser success guarantee.',
  'Earlier failed panels and diagnostic attempts remain preserved; standalone Booking successes do not retrospectively change a frozen panel.',
  'Native abilities and controlled API journeys are separate from public-site task completion.',
  'The additional 48801-48809 port range is parser/authority proof only; no socket or request used those ports.',
  'Timing categories overlap. Raw fixedWaitMs=0 omits the separately recorded 1500ms engine recovery delay; that delay remains included in elapsed goal/attempt time.',
  'BBC chronological discovery covers bounded pages only; no global latest/absence claim follows from missing links or an incomplete index.'],
 constraints:{explicitTaskPorts:[48721,48722,48723,48724,48725,48726,48727,48728,48729],stealth:false,credentialsRead:false,nasSync:false,publicRelease:false,globalInstallation:false,downloadsOver200MB:false,
  privateDesktopGuard:guard.guard,cleanup:reference('scripts/evidence/C2g-cleanup.json')},evidence};
fs.writeFileSync(output,JSON.stringify(seal,null,2)+'\n',{flag:'wx'});
const result={schema:'neyvia.efficiency-result.v1',id:'C2g-final-goal-cascade',study:'C2g frozen36 compiled/LAYA/Luna cascade and ordinary private engine recovery',
 method:'Fresh public pages, previously admitted observed routes, fresh goal checks, independently graded every-clause returned answers; failed and owner-wall attempts included',
 models:['compiled replay','frozen local LAYA g3-c2 CPU','gpt-6-luna low'],tasks:{description:'36 unchanged WebVoyager tasks across 12 sites',repetitions:1,independent_unit:'site/task group'},
 evidence_status:'raw-verified',limitations:seal.limitations,receipts:[{id:'seal',...reference(output),kind:'raw'}],
 metrics:[['success','count','passed'],['failed','count','failed'],['owner_needed','count','needsOwner'],['success_over_all','fraction','successOverAll'],['attempt_p50','ms','taskLatencyP50Ms'],['successful_goal_p50','ms','successfulGoalLatencyP50Ms'],['known_provider_tokens','tokens','knownProviderTokens']].map(([name,unit,key])=>({name,unit,value:seal.metrics[key],calculation:{receipt:'seal',pointer:'/metrics/'+key},ci_request:{method:'not-estimable',reason:'One correlated warm panel'},ci:{method:'not-estimable',reason:'One correlated warm panel'}}))};
requireThat(!fs.readFileSync('docs/research/results.jsonl','utf8').includes('"id":"'+result.id+'"'),'Preserve existing efficiency result');
fs.appendFileSync('docs/research/results.jsonl',JSON.stringify(result)+'\n');
fs.appendFileSync('docs/research/efficiency-log.md',`\n## C2g final goal cascade\n\nIndependently graded ${seal.metrics.passed}/36 passed, ${seal.metrics.failed} failed, ${seal.metrics.needsOwner} owner walls. Attempt median ${(attemptMedian/1000).toFixed(2)} s; successful-goal median ${(goalMedian/1000).toFixed(2)} s. Requested target met: ${target.met}. Actual planner known tokens ${knownTokens}; ${unknownUsageAttempts} attempts have unknown usage; provider dollars are unmetered.\n\nCompiled replay now checks the full goal before a bounded calibrated LAYA decision and actual Luna planning. A single ordinary private WebView2 retry handles observed JavaScript/rendering failures. SSE, preferences, fonts, drag, fragment links and scroll captures have separate real engine proofs. Independent review, source/observation digests and closed desktop guards are bound in [C2g.json](../../scripts/evidence/C2g.json). Earlier panels and all diagnostic failures remain preserved. This warm correlated run is not a matched cold comparison. Parser admission of 48801-48809 does not establish sockets on that range.\n\nRemaining failures: ${seal.failures.map(g=>g.id+': '+g.reason).join(' | ')}\n`);
console.log(JSON.stringify({output,sha256:reference(output).sha256,summary:seal.summary,metrics:seal.metrics,target}));
