'use strict';
// Continue known acquisition in the ordinary engine after a rendering retry.
// Inputs are prior admitted controls/URLs, never prior returned answers.
const {taskPlan,recentDate}=require('./c2f_site_flows.cjs');
function routes(old,asOf){
 const paths=old.answerEvidence?.map(e=>e.observation?.path||e.observation)||[],urls=old.answerEvidence?.map(e=>e.url).filter(Boolean)||[];
 return [...new Set(old.observations.filter(r=>paths.includes(r.path)||urls.includes(r.url)).map(r=>r.url))].filter(u=>/^https?:/.test(u)).map(value=>{
  const u=new URL(value),from=recentDate(old.goal,asOf);
  if(from&&/^\d{4}-\d{2}-\d{2}$/.test(u.searchParams.get('date-from_date'))&&/^\d{4}-\d{2}-\d{2}$/.test(u.searchParams.get('date-to_date'))){u.searchParams.set('date-from_date',from);u.searchParams.set('date-to_date',String(asOf).slice(0,10));}
  return u.href;
 });
}
async function recover({definition,old,admitted,observation,open,observe,actStep,capture,record,budget,asOf}){
 let o=observation,steps=0;const used=new Set(),context={asOf,completedQueries:[],verifiedSeasons:[]};
 try {
 if(admitted){for(const url of routes(old,asOf)){if(steps>=budget)break;if(o.url===url){record({kind:'normal-engine-compiled-route-reused',url,navigationRetries:0});continue;}o=await open(url);capture(o);steps++;record({kind:'normal-engine-compiled-route',url,admission:'Prior independently passed observed route; answer not copied'});}
  if(!/(?:^|\.)booking\.com$/.test(new URL(o.url).hostname))return {observation:o,steps,context};
 }
 while(steps<budget){
  const plan=taskPlan(definition.goal,o,context);if(!plan.ok)break;
  const identity=JSON.stringify([o.url,o.revision,plan.href,plan.steps]);if(used.has(identity))break;used.add(identity);
  if(plan.kind==='follow'){o=await open(plan.href);capture(o);steps++;record({kind:'normal-engine-compiled-follow',plan});}
  else{
   if(steps+plan.steps.length>budget)break;
   for(const step of plan.steps){o=await observe();capture(o);const before=o;steps++;const called=await actStep(step,o);o=called.observation||called;capture(o);record({kind:'normal-engine-compiled-action',step,beforeUrl:before.url,afterUrl:o.url,verification:called.verification});}
  }
  if(o.authentication?.required||/captcha|^just a moment/i.test(o.title+' '+o.text.slice(0,1500)))break;
 }
 return {observation:o,steps,context};
 }catch(error){o=error.value?.observation||await observe();capture(o);record({kind:'normal-engine-compiled-frontier',reason:error.message,steps,replaySafe:false});return {observation:o,steps,context,error:error.message};}
}
module.exports={recover,routes};
