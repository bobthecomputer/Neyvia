// Replay prior verified control procedures against fresh pages; no golden answers.
'use strict';
const fs=require('node:fs'),crypto=require('node:crypto');
const {answer}=require('./c2f_answers.cjs');
const {taskPlan,filterApplied,recentDate,compiledSearch,resultDigest}=require('./c2f_site_flows.cjs');
const cascadeMode=process.argv.includes('--cascade');
const {runCascade}=require('./browser_task_cascade.cjs');
const goalClauses=cascadeMode?JSON.parse(fs.readFileSync('config/browser_goal_clauses.json')):{};
const port=Number(process.argv[2]),out=process.argv[3],parallel=Number(process.argv[4]||1);
// Owned ranges: the C2 track (48721-48739) and the release browser gate (49021-49029).
const ownedPort=p=>Number.isInteger(p)&&(p>=48721&&p<=48739||p>=49021&&p<=49029);
if(!ownedPort(port)||!out||fs.existsSync(out)||parallel<1||parallel>4)throw Error('Explicit owned port, fresh output and 1-4 workers required');
// --obscura-only keeps every task on the admitted Obscura engine: no WebView2 (Edge) retry.
const obscuraOnly=process.argv.includes('--obscura-only');
if(cascadeMode&&parallel!==1)throw Error('Live cascade must pace public sites one task at a time');
const profileName=process.argv.find(arg=>arg.startsWith('--profile='))?.slice(10)||'C2h persisted public profile';
const base=`http://127.0.0.1:${port}`,prior=JSON.parse(fs.readFileSync('scripts/evidence/C2d-webvoyager-final.json'));
const allTasks=JSON.parse(fs.readFileSync('scripts/evidence/C2-webvoyager-tasks.json')).tasks;
const taskFilter=process.argv.find(arg=>arg.startsWith('--task-ids='))?.slice(11).split(',');
if(taskFilter?.some(id=>!allTasks.some(task=>task.id===id)))throw Error('Unknown frozen task selection');
const tasks=taskFilter?allTasks.filter(task=>taskFilter.includes(task.id)):allTasks;
// Admission is a pass/fail bit from the previous independent proof, not answers.
const learnedRoutes=process.argv.includes('--learned-routes');
const admissions=learnedRoutes?JSON.parse(fs.readFileSync('scripts/evidence/C2d-webvoyager-grades.json')).grades.filter(g=>g.success).map(g=>g.id):[];
const report={schema:'neyvia.C2f.live-replay@1',startedAt:new Date().toISOString(),port,parallel,stealth:false,modelCalls:0,tokens:0,paidModelCostUSD:0,priorProcedureSource:'scripts/evidence/C2d-webvoyager-final.json',priorProcedureSha256:hash(fs.readFileSync('scripts/evidence/C2d-webvoyager-final.json')),tasks:[],calls:[],scope:'Fresh replay of actual previously verified semantic controls. Terminal evidence acquired is not a semantic pass. Independent grading required; reference answers are never loaded.'};
report.taskSetSha256=hash(fs.readFileSync('scripts/evidence/C2-webvoyager-tasks.json'));report.utcRunDate=report.startedAt.slice(0,10);
if(cascadeMode)Object.assign(report,{schema:'neyvia.C2g.live-cascade@1',goalCheck:'Every goal clause needs a returned answer and a quote bound to fresh observed document bytes',model:'gpt-6-luna',paidModelCostUSD:null});
const sourcePaths=['scripts/c2f_replay.cjs','scripts/c2f_answers.cjs','scripts/c2f_site_flows.cjs','scripts/c2g_compiled_recovery.cjs','scripts/c2g_booking_flow.cjs','scripts/browser_source_goals.cjs','scripts/browser_task_cascade.cjs','scripts/browser_luna.cjs','scripts/browser_completion.cjs','scripts/browser_goal_checks.cjs','config/browser_goal_clauses.json','src/grant_agent/browser_site_manuals.py','src/grant_agent/browser_task.py','src/grant_agent/browser_scripts.py','src/grant_agent/neyvia_browser.py','src/grant_agent/browser_obscura.py','src/grant_agent/browser_dom.js','src-tauri/src/browser_projection.js'];
if(cascadeMode)report.sourcesAtStart=Object.fromEntries(sourcePaths.map(p=>[p,hash(fs.readFileSync(p))]));
let cookie;function hash(b){return crypto.createHash('sha256').update(b).digest('hex');}function save(){fs.writeFileSync(out,JSON.stringify(report,null,2)+'\n');}
async function call(op,args={},task){const t=performance.now(),r={op,taskId:task?.id,at:new Date().toISOString()};report.calls.push(r);try{const response=await fetch(base+'/api/ui/browser',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:JSON.stringify({op,args}),signal:AbortSignal.timeout(60000)});const v=await response.json();r.ok=v.ok;r.http=response.status;r.pageToClMs=(v.observation||v).latencyMs?.pageToCl;r.actionToVerifiedMs=v.latencyMs?.actionToVerified;r.verifiedActionSamples=(v.receipts||[]).map(x=>x.latencyMs?.actionToVerified).filter(Number.isFinite);if(!response.ok||v.ok===false){r.error=v.error||v.status;const e=Error(JSON.stringify(v));e.value=v;throw e;}if(cascadeMode&&v.actionId&&v.status==='queued'&&op!=='wait'){const waited=await call('wait',{actionId:v.actionId,timeoutMs:30000},task);const result=waited.result||waited;return op==='observe'?(result.observation||result):{...v,...result};}return v;}catch(e){r.error=e.message;throw e;}finally{r.ms=performance.now()-t;save();}}
function receiptActions(receipts){return new Set((receipts||[]).map((receipt,index)=>receipt.index??index)).size;}
function failedFlow(t,kind,failure,extra){const receipts=failure?.receipts||[];const attempted=receiptActions(receipts);t.steps+=attempted;
  const dispatched=new Set(receipts.filter(r=>r.actionId||typeof r.verification?.verified==='boolean').map(r=>r.index)).size;
  t.flow.push({kind,failed:true,...extra,error:failure?.error,receipts,attemptedActions:attempted,dispatchedActions:dispatched,dispatchCountBoundary:'Known receipts only; effects may be uncertain and no automatic action replay occurs'});}
const keys=['role','name','inputName','placeholder','frame'];function target(e){return Object.fromEntries(keys.filter(k=>e[k]!==undefined).map(k=>[k,e[k]]));}
function compile(old){const observations=old.observations.map(r=>({ref:r,obs:JSON.parse(fs.readFileSync(r.path))}));const flow=[];
 for(const event of old.trace){if(event.kind==='batch'){for(const receipt of event.receipts||[]){if(receipt.status==='failed'||receipt.verification?.verified!==true)continue;const s=event.steps[receipt.index];if(s)flow.push({kind:'action',step:s});}}
 else if(event.kind==='action'&&event.response?.verification?.verified){const o=observations.find(({obs})=>obs.revision===event.action.revision)?.obs;const e=o?.elements.find(e=>e.id===event.action.element);if(e)flow.push({kind:'action',step:{target:target(e),action:event.action.action,...(event.action.value===undefined?{}:{value:event.action.value}),...(event.action.expect?{expect:event.action.expect}:{})}});}
 else if(event.kind==='follow'){const e=observations.flatMap(({obs})=>obs.elements).find(e=>e.href===event.href);if(e)flow.push({kind:'follow',target:target(e),observedHref:event.href});}}
 return flow;}
function wall(o){return !!require('./browser_task_cascade.cjs').access(o);}
function snapshot(t,o){const p=out.replace(/\.json$/,'')+'-observations/'+t.id.replace(/[^a-z0-9-]/gi,'_')+'-'+t.observations.length+'.json';fs.mkdirSync(require('node:path').dirname(p),{recursive:true});const b=JSON.stringify(o)+'\n';fs.writeFileSync(p,b);t.observations.push({path:p,sha256:hash(b),url:o.url,revision:o.revision});save();return o;}
async function normalCookieChoice(t,tabId,observation,budget){
 const host=new URL(observation.url).hostname;
 const consentKey=(t.engine||'obscura')+':'+host;t.cookieChoices??=[];
 if(t.cookieChoices.includes(consentKey)||!(/(?:^|\.)google\.[a-z.]+$/i.test(host)||/(?:^|\.)espn\.(?:com|co\.uk)$/.test(host))||t.steps+1>budget)return observation;
 const controls=observation.elements.filter(row=>row.role==='button'&&row.enabled!==false&&!row.secret&&row.actions?.includes('click')&&/^(?:Reject all|Tout refuser)$/i.test(row.name.trim()));
 if(controls.length!==1)return observation;
 t.cookieChoices.push(consentKey);const steps=[{action:'click',target:target(controls[0])}];let result;
 try{result=await call('action.batch',{tabId,revision:observation.revision,steps},t);}catch(error){failedFlow(t,'normal-cookie-choice',error.value,{choice:controls[0].name});throw error;}
 t.steps+=receiptActions(result.receipts);t.flow.push({kind:'normal-cookie-choice',choice:controls[0].name,beforeUrl:observation.url,afterUrl:result.observation.url,receipts:result.receipts,authority:'Explicit privacy-preserving normal consent choice; no CAPTCHA/login/URL-parameter bypass'});
 return snapshot(t,result.observation);
}
async function cascade(t,tabId,spaceId,definition){
 let currentTab=tabId;
 const initial=JSON.parse(fs.readFileSync(t.observations.at(-1).path));
 async function readyNative(){
  await call('layout',{tabs:[{tabId:currentTab,x:0,y:0,width:1280,height:900,visible:true}]},t);
  const deadline=Date.now()+15000;let observation;
  do{observation=await call('observe',{tabId:currentTab},t);
   const resultReady=/wolframalpha\.com\/input/.test(observation.url)?require('./browser_source_goals.cjs').calculationReady(observation):
    /apple\.com\/newsroom\/search/.test(observation.url)?observation.elements?.some(e=>e.href&&/\/newsroom\/(?:19|20)\d{2}\//.test(e.href))||/no results|did not match/i.test(observation.text):
    /allrecipes\.com/.test(observation.url)?observation.text?.length>500:observation.text?.trim().length>100;
   if(observation.readyState==='complete'&&resultReady&&(observation.text?.trim()||observation.elements?.length||/captcha|just a moment/i.test(observation.title)))break;
   await new Promise(r=>setTimeout(r,250));
  }while(Date.now()<deadline);
  await call('tab.grant',{tabId:currentTab,enabled:true},t);return call('observe',{tabId:currentTab},t);
 }
 const transport=async(op,args)=>{
  if(op==='follow'){
   const supplied=JSON.parse(fs.readFileSync(t.observations.at(-1).path)),here=new URL(supplied.url),next=new URL(args.url);
   if(here.origin===next.origin&&here.pathname===next.pathname&&here.search===next.search&&here.hash!==next.hash)return transport('action',{element:args.element,action:'click'});
   const previous=currentTab;currentTab=(await call('tab.open',{url:args.url,engine:t.engine||'obscura',spaceId},t)).tabId;
   await call('tab.grant',{tabId:currentTab,enabled:true},t);const observation=t.engine==='webview2'?await readyNative():await call('observe',{tabId:currentTab},t);
   await call('tab.close',{tabId:previous},t);return {observation};
  }
  if(op==='action'){
   const supplied=JSON.parse(fs.readFileSync(t.observations.at(-1).path)),element=supplied.elements.find(e=>e.id===args.element);
   if(!element)throw Error('Model action has no captured semantic target');
   if(t.engine==='webview2')await call('tab.grant',{tabId:currentTab,enabled:true},t);
   const fresh=await call('observe',{tabId:currentTab},t);snapshot(t,fresh);
   if(fresh.url!==supplied.url)throw Object.assign(Error('Navigation changed during model planning; refresh before dispatch'),{value:{error:{code:'navigation_changed'},observation:fresh,dispatched:false}});
   const identity=target(element),matches=fresh.elements.filter(row=>row.enabled!==false&&!row.secret&&Object.entries(identity).every(([key,value])=>row[key]===value));
   if(matches.length>1&&matches.some(row=>row.id===element.id))identity.id=element.id;
   const step={target:identity,action:args.action,...(args.value===undefined?{}:{value:args.value}),...(args.expect?{expect:args.expect}:{})};
   return call('action.batch',{tabId:currentTab,revision:fresh.revision,steps:[step]},t);
  }
  return call(op,{...args,tabId:currentTab},t);
 };
 const result=await runCascade({goal:t.goal,requirements:goalClauses[t.id],observation:initial,
  documents:()=>t.observations.map(ref=>JSON.parse(fs.readFileSync(ref.path))),
  // The preceding C2f phase already ran compiled routes. Its acquisition bit
  // deliberately fails the whole-goal gate until all clauses are supported.
  compiled:async(o,usedActions=0)=>{let nativeSteps=0;
   if(t.engine==='webview2'&&!t.compiledInNative){t.compiledInNative=true;
    const recovered=await require('./c2g_compiled_recovery.cjs').recover({definition,old:prior.tasks.find(row=>row.id===t.id),admitted:learnedRoutes&&admissions.includes(t.id),observation:o,
     budget:Math.max(0,definition.maxActions-t.steps-usedActions),asOf:report.startedAt,capture:value=>snapshot(t,value),record:row=>{t.flow.push(row);save();},
     observe:()=>call('observe',{tabId:currentTab},t),
     open:async url=>{const old=currentTab;currentTab=(await call('tab.open',{url,engine:'webview2',spaceId},t)).tabId;const fresh=await readyNative();await call('tab.close',{tabId:old},t);return fresh;},
     actStep:async(step,fresh)=>{await call('tab.grant',{tabId:currentTab,enabled:true},t);fresh=await call('observe',{tabId:currentTab},t);snapshot(t,fresh);const rows=fresh.elements.filter(row=>row.enabled!==false&&!row.secret&&Object.entries(step.target).every(([key,value])=>row[key]===value));if(rows.length!==1)throw Error('Compiled normal-engine target changed or ambiguous');const effect=await call('action',{tabId:currentTab,revision:fresh.revision,element:rows[0].id,action:step.action,...(step.value===undefined?{}:{value:step.value}),...(step.expect?{expect:step.expect}:{})},t);if(step.action==='submit'||step.action==='click')effect.observation=await readyNative();return effect;}});
    o=recovered.observation;nativeSteps=recovered.steps;t.nativeCompiledContext=recovered.context;
   }
   const documents=t.observations.map(ref=>({ref,observation:JSON.parse(fs.readFileSync(ref.path))}));
   const extracted=answer(t.goal,documents,{asOf:report.startedAt}),verification=require('./browser_goal_checks.cjs').verify(t.goal,extracted,documents.map(d=>d.observation),report.startedAt);
   return {observation:o,answer:extracted.answer||extracted,verification,steps:nativeSteps};},
  acceptModelCompletion:(_decision,docs)=>{if(!/(?:^|\.)booking\.com$/.test(new URL(initial.url).hostname))return null;const documents=docs.map(observation=>({observation,ref:{}})),extracted=answer(t.goal,documents,{asOf:report.startedAt}),checked=require('./browser_goal_checks.cjs').verify(t.goal,extracted,docs,report.startedAt);return checked.checks.length?checked:null;},
  call:transport,capture:o=>snapshot(t,o),maxActions:Math.max(0,definition.maxActions-t.steps),
  rendererFailure:!!t.navigationFrontier||!!t.flow.find(f=>f.failed&&['stale_projection','effect_unconfirmed','invalid_target','missing_target','action_failed'].includes(f.error?.code)||f.filterVerification?.verified===false)||(/booking\.com\/searchresults/.test(initial.url)&&require('./c2g_booking_flow.cjs').resultCards(initial).some(card=>!card.price)),
  layaContext:o=>{
   const plan=taskPlan(t.goal,o,{asOf:report.startedAt,completedQueries:[],verifiedSeasons:[]});
   const step=plan.steps?.length===1&&plan.steps[0];if(step?.action!=='click')return null;
   const target=o.elements.filter(e=>e.enabled!==false&&!e.secret&&e.actions?.includes('click')&&Object.entries(step.target).every(([k,v])=>e[k]===v));
   const other=o.elements.find(e=>e.enabled!==false&&!e.secret&&e.actions?.includes('click')&&e.name?.trim()&&e.name!==target[0]?.name);
   if(target.length!==1||!other)return null;
   const canonical=e=>`Click ${e.role} "${e.name.replace(/\s+/g,' ').trim()}".`;
   return {goal:canonical(target[0]),decision_profile:'public_explicit_intent@1',options:[{id:'a',description:canonical(target[0]),args:{element:target[0].id,action:'click'}},{id:'b',description:canonical(other),args:{element:other.id,action:'click'}}]};
  },
  directory:require('node:path').resolve('.agent_control/C2g/planner',t.id.replace(/[^a-z0-9-]/gi,'_')),
  onStage:s=>{t.cascade??=[];t.cascade.push(s);save();},
  engineRetry:obscuraOnly?undefined:async(o,reason)=>{
   const runtime=await call('state',{},t);if(!runtime.runtime?.connected)throw Error('Normal WebView2 engine unavailable on the agent private desktop');
   const launch='.agent_control/C2g/private-native-'+port+'/launch.json';
   if(!fs.existsSync(launch)||JSON.parse(fs.readFileSync(launch)).route!=='agent-private-desktop')throw Error('Private-desktop native launcher receipt required');
   await new Promise(r=>setTimeout(r,1500));t.engine='webview2';
   const retryUrl=/\/shop\/unsupported/i.test(o.url)?t.initialRoute?.url||t.learnedRouteSource?.documents?.at(-1)?.url||o.url:o.url;
   const previous=currentTab;currentTab=(await call('tab.open',{url:retryUrl,engine:'webview2',spaceId},t)).tabId;
   await call('tab.grant',{tabId:currentTab,enabled:true},t);let next=await readyNative();
   next=await normalCookieChoice(t,currentTab,next,definition.maxActions);await call('tab.close',{tabId:previous},t);
   t.flow.push({kind:'normal-engine-retry',reason,from:'obscura',to:'webview2',url:o.url,attempt:1,politeDelayMs:1500,stealth:false});return next;
  }});
 t.steps+=result.steps;t.status=result.status;t.reason=result.reason;t.answer=result.answer||null;t.goalVerified=result.verification?.verified===true;t.goalVerification=result.verification;
 t.modelReceipts=result.modelCalls;t.tokens=result.modelCalls.reduce((a,r)=>a+(r.usage?.input_tokens||0)+(r.usage?.output_tokens||0),0);t.modelCalls=result.modelCalls.length;
 t.paidModelCostUSD=null;t.final={url:result.observation.url,title:result.observation.title,text:result.observation.text,tables:result.observation.tables,truncated:result.observation.truncated};
 report.modelCalls+=t.modelCalls;report.tokens+=t.tokens;return currentTab;
}
async function run(def,spaceId){const start=performance.now(),t={id:def.id,goal:def.goal,startUrl:def.startUrl,startedAt:new Date().toISOString(),status:'running',steps:0,observations:[],flow:[],tokens:0,paidModelCostUSD:0};report.tasks.push(t);let tab;
 try{const old=prior.tasks.find(x=>x.id===def.id);const flow=compile(old);t.compiledSteps=flow.length;
 if(!cascadeMode&&def.id==='Google Search--2') {t.status='needs_owner';t.reason='Existing News ordering CAPTCHA remains owner-only; no page acquisition or challenge attempt in this run';t.blockedEvidence='scripts/evidence/C2d.json#failures/Google Search--2';return;}
 const admittedUrls=learnedRoutes&&admissions.includes(def.id)?require('./c2g_compiled_recovery.cjs').routes(old,report.startedAt):[];
 const direct=admittedUrls[0]&&!/booking\.com$/.test(new URL(admittedUrls[0]).hostname)?admittedUrls[0]:null;
 if(direct){t.initialRoute={url:direct,admission:'Prior independently passed observed route',source:'scripts/evidence/C2d-webvoyager-grades.json',startUrl:def.startUrl};t.steps++;t.flow.push({kind:'compiled-initial-route',...t.initialRoute});}
 tab=(await call('tab.open',{url:direct||def.startUrl,engine:'obscura',spaceId},t)).tabId;await call('tab.grant',{tabId:tab,enabled:true},t);let o=snapshot(t,await call('observe',{tabId:tab},t));o=await normalCookieChoice(t,tab,o,def.maxActions);if(wall(o)){t.status='needs_owner';throw Error('Observed automation/login wall: '+o.title);}
 if(cascadeMode){const docs=t.observations.map(ref=>({ref,observation:JSON.parse(fs.readFileSync(ref.path))})),candidate=answer(t.goal,docs,{asOf:report.startedAt}),checked=require('./browser_goal_checks.cjs').verify(t.goal,candidate,docs.map(d=>d.observation),report.startedAt);if(checked.verified){t.initialGoalAlreadyMet=true;t.status='evidence_acquired';return;}}
 if(learnedRoutes&&admissions.includes(def.id)){
   const sources=old.answerEvidence?.map(e=>e.observation?.path||e.observation)||[];
   const sourceUrls=old.answerEvidence?.map(e=>e.url).filter(Boolean)||[];
   const documents=old.observations.filter(r=>sources.includes(r.path)||sourceUrls.includes(r.url));
   if(!documents.length)throw Error('Previously passed route has no bound observed evidence documents');
   const urls=[...new Set(documents.map(r=>r.url))].filter(url=>/^https?:/.test(url));
   t.learnedRouteSource={admission:'previous independently passed first success',gradeReceipt:'scripts/evidence/C2d-webvoyager-grades.json',gradeReceiptSha256:hash(fs.readFileSync('scripts/evidence/C2d-webvoyager-grades.json')),documents:documents.map(r=>({path:r.path,sha256:r.sha256,url:r.url}))};
   for(const observedUrl of urls){let url=observedUrl;const range=recentDate(def.goal,report.startedAt),u=new URL(url);
     if(range&&/^\d{4}-\d{2}-\d{2}$/.test(u.searchParams.get('date-from_date'))&&/^\d{4}-\d{2}-\d{2}$/.test(u.searchParams.get('date-to_date'))){u.searchParams.set('date-from_date',range);u.searchParams.set('date-to_date',report.utcRunDate);url=u.href;t.dateInputs={from:range,to:report.utcRunDate,sourceUrl:observedUrl,template:'Previously observed date-from_date/date-to_date parameters; no new route or answer'};}
     if(/recent papers.*select one.*abstract/i.test(t.goal)&&/^\/abs\//.test(new URL(url).pathname)&&/^\/list\/[^/]+\/recent$/.test(new URL(o.url).pathname)){
      const result=o.elements.find(e=>e.href&&/^https:\/\/arxiv\.org\/abs\//.test(e.href));if(!result)throw Error('Compiled abstract selection requires a fresh observed recent-list paper');url=result.href;t.flow.push({kind:'compiled-fresh-result-route',url,previouslyObservedURL:observedUrl,binding:'One current recent-list paper, never a saved paper answer'});
     }
     if(o.url===url)continue;
     const before=tab;tab=(await call('tab.open',{url,engine:'obscura',spaceId},t)).tabId;await call('tab.grant',{tabId:tab,enabled:true},t);o=snapshot(t,await call('observe',{tabId:tab},t));await call('tab.close',{tabId:before},t);t.steps++;o=await normalCookieChoice(t,tab,o,def.maxActions);if(wall(o)){t.status='needs_owner';throw Error('Observed learned-route automation/login wall: '+o.title);}}
   t.status='evidence_acquired';t.goalVerified=false;t.final={url:o.url,title:o.title,text:o.text.slice(0,24000),tables:o.tables,truncated:o.truncated};return;
 }
 const advisory=await call('decide',{tabId:tab,question:'calibrated_advisory',context:{goal:'What is the observed document loading state?',decision_profile:'public_observed_fields@1',advisory_field:'readyState',options:[{id:'a',description:o.readyState},{id:'b',description:o.readyState==='complete'?'loading':'complete'}]}},t).catch(e=>({status:'unavailable',error:e.message}));
 const inference=advisory.decision?.runtime?.total_ms??advisory.latency_ms?.model;t.layaInferenceMs=typeof inference==='number'&&Number.isFinite(inference)?inference:null;
 t.laya={accepted:advisory.accepted_decision,policy:advisory.decision_policy,status:advisory.status,reportedTiming:advisory.timing||advisory.timings||advisory.latencyMs||null};
 const planned=new Set(),context={asOf:report.startedAt,completedQueries:[],verifiedSeasons:[]};
 let safeRefreshes=0;
 for(let round=0;round<def.maxActions;round++){
   let plan=taskPlan(def.goal,o,context);
   if(plan.query&&!context.compiledManualChecked){
     context.compiledManualChecked=true;const manual=await call('site.manual',{tabId:tab},t);o=snapshot(t,manual.observation);
     plan=taskPlan(def.goal,o,context);const procedure=compiledSearch(manual.compiledProcedures,plan.query,o);
     if(procedure&&t.steps+procedure.steps.length<=def.maxActions){
       let result;try{result=await call('script.run',{tabId:tab,name:procedure.name,inputs:procedure.inputs},t);}catch(error){failedFlow(t,'compiled-search',error.value,{name:procedure.name,inputBindings:procedure.inputBindings});throw error;}o=snapshot(t,result.observation);t.steps+=receiptActions(result.receipts);
       t.flow.push({kind:'compiled-search',name:procedure.name,inputBindings:procedure.inputBindings,inputs:procedure.inputs,admission:procedure.admission,receipts:result.receipts,verification:result.verification,earlyExit:result.earlyExit,modelCalls:result.modelCalls,tokens:result.tokens});continue;
     }
   }
   if(!plan.ok){t.plannerFrontier=plan.frontier;break;}
   const identity=JSON.stringify({url:o.url,kind:plan.kind,steps:plan.steps,href:plan.href});if(planned.has(identity)){t.plannerFrontier='Already dispatched procedure; no blind replay';break;}planned.add(identity);
   const plannedActions=plan.kind==='follow'?1:plan.steps.length;if(t.steps+plannedActions>def.maxActions){t.plannerFrontier='Frozen action budget would be exceeded; retain partial evidence';break;}
   if(plan.kind==='follow'){const previous=tab;tab=(await call('tab.open',{url:plan.href,engine:'obscura',spaceId},t)).tabId;await call('tab.grant',{tabId:tab,enabled:true},t);o=snapshot(t,await call('observe',{tabId:tab},t));await call('tab.close',{tabId:previous},t);t.flow.push({kind:'observed-follow',plan});t.steps++;}
   else {const before=o;let result;
     try{result=await call('action.batch',{tabId:tab,revision:o.revision,steps:plan.steps},t);}
     catch(error){const failure=error.value,code=failure?.error?.code||failure?.code;
       if(code==='stale_projection'&&!(failure.receipts?.length)&&!failure.actionId&&safeRefreshes<2){safeRefreshes++;t.safePreDispatchRefreshes=safeRefreshes;planned.delete(identity);o=snapshot(t,await call('observe',{tabId:tab},t));t.flow.push({kind:'safe-pre-dispatch-refresh',code,dispatched:0});continue;}failedFlow(t,'grounded-repair',failure,{plan});throw error;}
     o=snapshot(t,result.observation);t.steps+=result.receipts.length;t.flow.push({kind:'grounded-repair',plan,receipts:result.receipts});if(plan.beforeResultDigest){const guard=filterApplied(before,o,plan);t.flow.at(-1).filterVerification=guard;if(!guard.verified)throw Error('Select changed without verified result filtering');}if(plan.sortBeforeResultDigest){const u=new URL(o.url);t.flow.at(-1).sortVerification={selectedDescendingStarOrder:u.searchParams.get('s')==='stars'&&u.searchParams.get('o')==='desc',resultsChanged:plan.sortBeforeResultDigest!==resultDigest(o),beforeResultDigest:plan.sortBeforeResultDigest,afterResultDigest:resultDigest(o)};}if(plan.steps.some(s=>s.action==='submit'||s.action==='fill')){t.queryProcedures??=[];t.queryProcedures.push({query:plan.query,url:o.url,effectsVerified:true});}}
   if(wall(o)){t.status='needs_owner';throw Error('Observed automation/login wall: '+o.title);}
 }
 if(context.searchPages&&!context.coverage)context.coverage={complete:false,reason:'Finite action budget does not cover all chronological search results',pages:context.searchPages,articles:context.readDocuments?.map(d=>d.url)};
 t.plannerContext={completedQueries:context.completedQueries,productEvidence:context.productEvidence,verifiedSeasons:context.verifiedSeasons,seasonEvidence:context.seasonEvidence,coverage:context.coverage,repositorySearch:context.repositorySearch,readDocuments:context.readDocuments?.map(d=>({url:d.url,title:d.title,dates:d.dates,truncated:d.truncated}))};
 if(t.flow.some(event=>event.kind!=='safe-pre-dispatch-refresh')){t.status='evidence_acquired';t.goalVerified=false;t.final={url:o.url,title:o.title,text:o.text,tables:o.tables,truncated:o.truncated};return;}
 for(let i=0;i<flow.length;){if(t.steps>=def.maxActions)throw Error('Frozen action budget exhausted');const item=flow[i];
 if(item.kind==='follow'){const exact=o.elements.filter(e=>e.enabled&&!e.secret&&e.href===item.observedHref);const semantic=o.elements.filter(e=>e.enabled&&!e.secret&&e.href&&Object.entries(item.target).every(([k,v])=>e[k]===v));const candidates=exact.length===1?exact:semantic;if(candidates.length!==1)throw Error('Learned link changed; new planning required: '+item.target.name);const prev=tab;tab=(await call('tab.open',{url:candidates[0].href,engine:'obscura',spaceId},t)).tabId;await call('tab.grant',{tabId:tab,enabled:true},t);o=snapshot(t,await call('observe',{tabId:tab},t));await call('tab.close',{tabId:prev},t);t.steps++;t.flow.push({kind:'follow',url:o.url});i++;}
 else{const steps=[];while(i<flow.length&&flow[i].kind==='action'&&steps.length<Math.min(8,def.maxActions-t.steps)){steps.push(flow[i].step);i++;}let result;try{result=await call('action.batch',{tabId:tab,revision:o.revision,steps},t);}catch(error){failedFlow(t,'batch',error.value,{steps});throw error;}t.steps+=result.receipts.length;t.flow.push({kind:'batch',steps,receipts:result.receipts});o=snapshot(t,result.observation);}
 if(wall(o)){t.status='needs_owner';throw Error('Observed automation/login wall: '+o.title);}}
 t.status=flow.length?'evidence_acquired':'frontier';t.goalVerified=false;t.final={url:o.url,title:o.title,text:o.text.slice(0,24000),tables:o.tables,truncated:o.truncated};if(!flow.length)t.reason='No verified prior control procedure; planning required';
 }catch(e){if(t.status==='running')t.status='frontier';t.reason=e.message.slice(0,2000);const failedCall=report.calls.findLast(c=>c.taskId===t.id&&c.error);if(failedCall?.op==='tab.open'&&t.observations.length)t.navigationFrontier={op:failedCall.op,error:failedCall.error,ms:failedCall.ms,authority:'Observed headless navigation failure; one ordinary engine recovery, no failed effect replay'};if(e.value?.observation)snapshot(t,e.value.observation);}
 finally{if(cascadeMode&&tab&&t.observations.length){try{tab=await cascade(t,tab,spaceId,def);}catch(error){t.status='frontier';t.reason='Cascade transport failed: '+error.message;t.goalVerified=false;}}const extractionStart=performance.now();if(!cascadeMode&&t.status==='evidence_acquired'){t.answer=answer(t.goal,t.observations.slice(1).map(ref=>({ref,observation:JSON.parse(fs.readFileSync(ref.path))})));t.answerReturnedAt=new Date().toISOString();}if(cascadeMode&&t.answer)t.answerReturnedAt=new Date().toISOString();t.extractionMs=performance.now()-extractionStart;t.elapsedMs=performance.now()-start;t.finishedAt=new Date().toISOString();const calls=report.calls.filter(c=>c.taskId===t.id);t.timing={browserCallMs:calls.filter(c=>c.op!=='wait').reduce((a,c)=>a+(c.ms||0),0),pageLoadMs:calls.filter(c=>c.op==='tab.open').reduce((a,c)=>a+(c.ms||0),0),modelMs:t.layaInferenceMs??null,layaCallMs:calls.filter(c=>c.op==='decide').reduce((a,c)=>a+(c.ms||0),0),hostModelMs:(t.modelReceipts||[]).reduce((sum,receipt)=>sum+(receipt.ms||0),0),fixedWaitMs:0,safePreDispatchRefreshes:t.safePreDispatchRefreshes||0,actionReplays:0,retries:t.safePreDispatchRefreshes||0};t.timing.executorMs=t.elapsedMs-t.timing.browserCallMs;t.timing.scope='Browser HTTP total includes page-load and adviser-call subsets; categories overlap and must not be summed. Local inference is null when provider gives no trustworthy breakdown. Cleanup excluded from goal completion.';const cleanupStart=performance.now();if(tab&&t.status==='needs_owner'){try{const h=await call('task.pause',{tabId:tab,goal:t.goal,requirements:goalClauses[t.id],allowModel:true,maxActions:Math.min(24,def.maxActions),maxModelCalls:8},t);t.ownerHandoff={taskId:h.taskId,tabId:tab,prompt:h.prompt,paneStatus:h.paneStatus};t.goalVerified=false;}catch(e){t.handoffError=e.message;}}else if(tab)await call('tab.close',{tabId:tab},t).catch(e=>t.closeError=e.message);t.cleanupMs=performance.now()-cleanupStart;t.cleanupFinishedAt=new Date().toISOString();save();console.log(JSON.stringify({id:t.id,status:t.status,ms:Math.round(t.elapsedMs),reason:t.reason?.slice(0,160)}));}}
(async()=>{const r=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(!r.ok)throw Error('Owner local session bootstrap failed');cookie=r.headers.get('set-cookie').split(';')[0];const state=await call('state');let profile=state.profiles.find(p=>p.name===profileName);if(!profile)profile=await call('profile.create',{name:profileName});let space=state.spaces.find(s=>s.profileId===profile.id&&s.name===profileName);if(!space)space=await call('space.create',{name:profileName,profileId:profile.id});report.persistedProfile={profileId:profile.id,spaceId:space.id,name:profileName};for(const task of tasks){await run(task,space.id);await new Promise(r=>setTimeout(r,1500));}report.finishedAt=new Date().toISOString();if(cascadeMode){report.sourcesAtFinish=Object.fromEntries(sourcePaths.map(p=>[p,hash(fs.readFileSync(p))]));report.sourcesUnchanged=JSON.stringify(report.sourcesAtStart)===JSON.stringify(report.sourcesAtFinish);}save();})().catch(e=>{report.fatal=e.stack;save();process.exitCode=1;console.error(e.stack);});
