'use strict';
// Shared host driver: compiled acquisition -> calibrated LAYA -> typed Luna.
// Callers provide actual browser transport, snapshots and explicit goal clauses.
const {decide}=require('./browser_luna.cjs');
const {LoopGuidance}=require('./browser_completion.cjs');
const norm=s=>String(s??'').replace(/\s+/gu,' ').trim();
function access(observation){
 const content=observation.title+' '+(observation.text||'').slice(0,5000);
 const u=new URL(observation.url);
 if(/(?:^|\.)google\.[a-z.]+$/.test(u.hostname)&&/^\/sorry\//.test(u.pathname)&&/trafic exceptionnel|non un robot|unusual traffic/i.test(content))return 'access_wall';
 const captcha=/recaptcha|hcaptcha|captcha|verify (?:you are|that you are) human|unusual traffic/i.test(content)||
  (observation.frames||[]).some(f=>/recaptcha|hcaptcha/i.test(f.url||f.src||''));
 if(captcha)return 'captcha';
 if(/^just a moment|checking (?:your )?browser|javascript.*(?:enable|challenge)|challenge.*javascript/i.test(content.trim()))return 'javascript';
 if(observation.authentication?.required)return 'authentication';
 if(/access denied|security check/i.test(content))return 'access_wall';
 return null;
}
function checkGoal(decision,requirements,documents){
 const clauses=decision.clauses||[],failures=[];
 if(decision.status!=='done'||!norm(decision.answer))failures.push('No complete returned answer');
 for(const requirement of requirements){
  const rows=clauses.filter(c=>norm(c.requirement)===norm(requirement));
  if(rows.length!==1||rows[0].met!==true){failures.push(requirement);continue;}
  const c=rows[0],doc=Number.isInteger(c.document)&&c.document>=0?documents[c.document]:null,text=doc?norm([doc.url,doc.title,doc.text,JSON.stringify(doc.tables||[]),JSON.stringify(doc.elements?.filter(e=>e.role==='image').map(e=>e.name)||[])].join(' ')):'';
  const quotes=[c.quote,...(c.quotes||[])].filter(v=>norm(v));
  if(!quotes.length||quotes.some(quote=>!text.includes(norm(quote))))failures.push('Fresh evidence absent: '+requirement);
 }
 return {verified:failures.length===0,failures,clauses};
}
async function runCascade({goal,requirements,observation,documents,compiled,acceptModelCompletion,call,capture,engineRetry,rendererFailure,layaContext,maxActions=16,directory,onStage=()=>{}}){
 if(!Array.isArray(requirements)||!requirements.length||requirements.some(x=>typeof x!=='string'||!x.trim()))throw Error('Explicit independent goal clauses required');
 const stages=[],record=v=>{stages.push(v);onStage(v);},modelCalls=[],acted=new Set(),uncertain=new Set(),loop=new LoopGuidance();let o=observation,nativeAttempted=false,readinessRefreshes=0,safeRefreshes=0,invalidPlans=0,completionCorrections=0,steps=0,completed=null;
 async function judge(answer,docs){try{const r=await decide({mode:'judge',goal,requirements,answer,documents:docs,previousStages:stages.slice(-10)},{directory});modelCalls.push(r.receipt);record({stage:'completion-judge',...r.decision,ms:r.receipt.ms});return r.decision;}
  catch(e){if(e.receipt)modelCalls.push(e.receipt);record({stage:'completion-judge',verdict:false,failure_reason:e.message});return {verdict:false,failure_reason:e.message};}}
 const actionKey=(a,page)=>JSON.stringify([page.url,a.kind,a.value,page.elements?.find(e=>e.id===a.element)?.name]);
 async function recoverEffect(error,action){
  const code=error.value?.error?.code;
  if(!['effect_unconfirmed','fresh_observation_unavailable'].includes(code))return false;
  loop.result(false);
  if(action)uncertain.add(actionKey(action,o));
  steps++;record({stage:'effect',status:'unconfirmed',code,action,dispatchReceipts:error.value?.receipts||[],replaySafe:false,steps});
  try{o=await call('observe',{});capture(o);record({stage:'read-only-recovery',status:'observed',actionReplays:0,effectVerified:false,afterUrl:o.url});return true;}
  catch(e){record({stage:'read-only-recovery',status:'failed',error:e.message,replaySafe:false});return false;}
 }
 async function replayCompiled(reason){
  if(!compiled)return;
  record({stage:'compiled',status:'start',reason,modelCalls:0});
  try{const r=await compiled(o,steps);o=r.observation||o;steps+=r.steps||0;capture(o);
   record({stage:'compiled',status:r.verification?.verified?'goal_verified':'goal_unverified',reason,verification:r.verification||null,steps:r.steps||0});
   if(r.verification?.verified&&r.answer){const verdict=await judge(r.answer,documents());if(verdict.verdict)completed={status:'answered',answer:r.answer,verification:r.verification,observation:o,stages,modelCalls,steps};}
  }catch(e){record({stage:'compiled',status:'frontier',error:e.message,replaySafe:false});}
 }
 async function retry(reason){
  if(nativeAttempted||!engineRetry)return false;nativeAttempted=true;
  record({stage:'engine',engine:'webview2',reason,attempt:1,stealth:false,authority:'One ordinary JavaScript-capable engine retry on the agent private desktop'});
  o=await engineRetry(o,reason);capture(o);await replayCompiled('ordinary_engine_recovery');return true;
 }
 async function boundary(){
  const wall=access(o);
  return wall?{status:'needs_owner',reason:'Observed '+wall+' wall; no solving, login or evasion',observation:o,stages,modelCalls,steps}:null;
 }
 const initial=await boundary();if(initial)return initial;if(completed)return completed;
 await replayCompiled('initial_goal_check');if(completed)return completed;
 const missingResult=()=>o.text.trim().length<100&&o.elements.length<5||/apple\.com\/newsroom\/search/.test(o.url)&&!o.elements.some(e=>e.href&&/\/newsroom\/(?:19|20)\d{2}\//.test(e.href))&&!/no results|did not match/i.test(o.text)||/wolframalpha\.com\/input/.test(o.url)&&!require('./browser_source_goals.cjs').calculationReady(o);
 if(missingResult()){
  const began=performance.now(),end=Date.now()+15000;let polls=0;
  while(missingResult()&&Date.now()<end){await new Promise(r=>setTimeout(r,200));o=await call('observe',{});capture(o);polls++;const wall=await boundary();if(wall)return wall;}
  record({stage:'readiness',engine:'obscura',polls,ms:performance.now()-began,resultReady:!missingResult(),actionReplays:0});
  await replayCompiled('after_read_only_readiness');if(completed)return completed;
 }
 if(/unsupportedbrowser|unsupported browser|upgrade your browser/i.test(o.url+' '+o.title+' '+o.text.slice(0,2000)))await retry('unsupported_headless_rendering');
 else if(rendererFailure||missingResult())await retry('insufficient_javascript_result_rendering');
 if(completed)return completed;
 const blocked=await boundary();if(blocked)return blocked;
 // LAYA's established calibration covers explicitly named controls only.
 // An unfamiliar whole-goal judgment is never accepted as calibrated confidence.
 const context=layaContext?.(o);
 if(context){let selected;
  try{const r=await call('decide',{question:'grounded_action',context});record({stage:'laya',status:r.status,policy:r.browser_policy,selectedAction:r.selected_action||null});selected=r.selected_action;
  }catch(e){record({stage:'laya',status:'unavailable',error:e.message});}
  if(selected&&steps<maxActions){try{const result=await call('action',selected);o=result.observation||o;capture(o);steps++;
    if(result.verification?.verified!==true&&!(result.receipts?.length&&result.receipts.every(r=>r.verification?.verified===true))){o=await call('observe',{});capture(o);record({stage:'read-only-recovery',status:'observed',actionReplays:0,effectVerified:false});}
   }catch(e){if(!await recoverEffect(e,{kind:selected.action,element:selected.element,value:selected.value})){record({stage:'effect',status:'failed',error:e.message,replaySafe:false});return {status:'frontier',reason:e.message,observation:o,stages,modelCalls,steps};}}}
 }else{
  // A measured LAYA readiness subdecision gives a truthful low-confidence
  // frontier for unsupported planning rather than fabricated model selection.
  try{const r=await call('decide',{question:'calibrated_advisory',context:{goal:'What is the observed document loading state?',decision_profile:'public_observed_fields@1',advisory_field:'readyState',options:[{id:'a',description:o.readyState||'loading'},{id:'b',description:o.readyState==='complete'?'loading':'complete'}]}});
   record({stage:'laya',status:r.status,acceptedDecision:r.accepted_decision,policy:r.decision_policy,goalVerified:false,reason:'Whole-goal planning exceeds the frozen calibrated scope'});
  }catch(e){record({stage:'laya',status:'unavailable',error:e.message});}
 }
 const modelRounds=Math.min(Math.max(0,maxActions-steps)+2,24);
 for(let round=0;round<modelRounds;round++){
  const b=await boundary();if(b)return b;if(completed)return completed;
  loop.page(o);
  const docs=[...new Map(documents().map(d=>[JSON.stringify([d.url,d.text,d.tables,d.elements?.filter(e=>e.role==='image').map(e=>e.name)]),d])).values()],input={goal,requirements,finishOnly:stages.at(-1)?.stage==='answer-required',loopNudge:loop.nudge(),uncertainActions:[...uncertain],current:{url:o.url,title:o.title,revision:o.revision,readyState:o.readyState,authentication:o.authentication,
   elements:o.elements.filter(e=>e.enabled!==false&&!e.secret).map(({id,role,name,value,actions,href,inputName,placeholder})=>({id,role,name,value,actions,href,inputName,placeholder}))},
   documents:docs.map((d,index)=>({index,url:d.url,title:d.title,text:d.text,tables:d.tables,images:d.elements?.filter(e=>e.role==='image').map(e=>e.name),truncated:d.truncated})),asOf:new Date().toISOString(),previousStages:stages.slice(-5)};
  let result;try{result=await decide(input,{directory});}catch(e){if(e.receipt)modelCalls.push(e.receipt);record({stage:'luna',status:'unavailable',error:e.message,toolAttempt:e.receipt?.toolAttempt,usage:e.receipt?.usage});return {status:'frontier',reason:e.message,observation:o,stages,modelCalls,steps};}
  modelCalls.push(result.receipt);const d=result.decision;
  record({stage:'luna',status:d.status,reason:d.reason,ms:result.receipt.ms,usage:result.receipt.usage});
  if(d.status==='done'){const verification=checkGoal(d,requirements,docs),sourceGoal=acceptModelCompletion?.(d,docs);if(sourceGoal?.verified===false){verification.verified=false;verification.failures.push(...sourceGoal.checks.filter(c=>!c.passed).map(c=>c.requirement));}record({stage:'goal',...verification,sourceGoal});
   if(verification.verified){const verdict=await judge(d.answer,docs);if(verdict.verdict)return {status:'answered',answer:d.answer,verification,observation:o,stages,modelCalls,steps};verification.verified=false;verification.failures.push(verdict.failure_reason);}
   record({stage:'citation-correction',status:'completion_rejected',reason:'Correct exact document index, source quotes and goal facts: '+verification.failures.join('; '),actionReplays:0});if(++completionCorrections>2)return {status:'frontier',reason:'Repeated unsupported goal completion; source requirements remain unmet',observation:o,stages,modelCalls,steps};continue;
  }
  if(d.status==='needs_owner')return {status:access(o)?'needs_owner':'frontier',reason:d.reason,observation:o,stages,modelCalls,steps};
  if(d.status==='act'&&d.action.kind==='none'){record({stage:'answer-required',reason:'No action dispatched. Return the complete requested answer with done if the cited facts satisfy every goal clause; otherwise frontier. A separate completion judge still verifies the answer.'});continue;}
  if(d.status!=='act'||steps>=maxActions)return {status:'frontier',reason:d.reason||'Bounded action budget exhausted',observation:o,stages,modelCalls,steps};
  const a=d.action,identity=JSON.stringify([o.revision,a]);loop.action(a,o);if(acted.has(identity)){loop.result(false);record({stage:'plan-rejected',reason:'Repeated unchanged plan; replan using fresh observation',dispatched:false});o=await call('observe',{});capture(o);continue;}acted.add(identity);
  if(a.kind==='native'){
   if(nativeAttempted&&readinessRefreshes<2){readinessRefreshes++;o=await call('observe',{});capture(o);record({stage:'readiness',engine:'webview2',navigationRetries:0,refresh:readinessRefreshes});continue;}
   if(!await retry('insufficient_javascript_result_rendering'))return {status:'frontier',reason:'One normal engine retry already used or unavailable',observation:o,stages,modelCalls,steps};if(completed)return completed;continue;
  }
  if(a.kind==='observe'){o=await call('observe',{});capture(o);continue;}
  const e=o.elements.find(e=>e.id===a.element&&e.enabled!==false&&!e.secret);
  if(uncertain.has(actionKey(a,o))){loop.result(false);record({stage:'plan-rejected',reason:'Original effect is uncertain; this replay was not dispatched',action:a,dispatched:false});o=await call('observe',{});capture(o);if(++invalidPlans>2)return {status:'frontier',reason:'Planner repeated an unconfirmed effect',observation:o,stages,modelCalls,steps};continue;}
  if(!e||!e.actions?.includes(a.kind==='follow'?'click':a.kind)){loop.result(false);record({stage:'plan-rejected',reason:'Action kind and element must match current supported actions; no effect dispatched',action:a,dispatched:false});if(++invalidPlans>2)return {status:'frontier',reason:'Planner repeatedly proposed an unavailable observed action',observation:o,stages,modelCalls,steps};continue;}
  try{const r=a.kind==='follow'?await call('follow',{url:e.href,element:e.id}):await call('action',{revision:o.revision,element:e.id,action:a.kind,...(['fill','select'].includes(a.kind)?{value:a.value}:{})});
   o=r.observation||r;capture(o);steps++;loop.result(true);record({stage:'action',action:a,steps,afterUrl:o.url,verification:r.verification||r.receipts?.map(x=>x.verification)});await replayCompiled('after_verified_action');if(completed)return completed;
  }catch(err){const code=err.value?.error?.code,receipt=err.value?.receipt;
   if(await recoverEffect(err,a))continue;
   if(safeRefreshes<2&&((code==='stale_projection'&&!receipt?.actionId)||(receipt?.nativeStatus==='stale_projection'&&receipt.dispatched===false)||(code==='navigation_changed'&&err.value.dispatched===false))){
    safeRefreshes++;record({stage:'pre-dispatch-refresh',status:'stale_projection',dispatched:false,count:safeRefreshes});o=await call('observe',{});capture(o);acted.delete(identity);continue;
   }
   record({stage:'effect',status:'failed',error:err.message.slice(0,2000),replaySafe:false});return {status:'frontier',reason:err.message.slice(0,2000),observation:o,stages,modelCalls,steps};}
 }
 return {status:'frontier',reason:'Bounded planner loop exhausted',observation:o,stages,modelCalls,steps};
}
module.exports={runCascade,checkGoal,access};
