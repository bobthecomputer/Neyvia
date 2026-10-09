/* Re-admit an actual previously successful CL search, then vary its input. */
'use strict';
const fs=require('node:fs'),crypto=require('node:crypto');
const [portText,priorPath,out,firstQuery,replayQuery]=process.argv.slice(2),port=Number(portText);
if(!Number.isInteger(port)||port<48721||port>48729||!priorPath||!out||fs.existsSync(out)||!firstQuery||!replayQuery)throw Error('Explicit assigned port, verified prior receipt, fresh output and two queries required');
const bytes=fs.readFileSync(priorPath),prior=JSON.parse(bytes),learnCall=prior.calls.find(c=>c.op==='script.learn');
if(!prior.ok||!prior.learn?.verification?.verified||!learnCall?.args?.steps?.length||!prior.learn.receipts?.every(r=>r.verification?.verified))throw Error('Prior search has no verified first success');
const sourceURL=prior.calls.find(c=>c.op==='tab.open')?.args?.url;
const pairs=[...new URL(prior.learn.observation.url).searchParams].filter(([,value])=>value===learnCall.args.inputs.query);
if(pairs.length!==1)throw Error('No uniquely observed successful query parameter');
const report={schema:'neyvia.C2f.live-compiled-search@1',startedAt:new Date().toISOString(),port,
 source:{path:priorPath,sha256:crypto.createHash('sha256').update(bytes).digest('hex')},
 boundary:'Actual observed search procedure and URL parameter re-admitted against fresh pages; article/date/latest goals are independently graded',calls:[],tokens:0,paidModelCostUSD:0};
const base='http://127.0.0.1:'+port,save=()=>fs.writeFileSync(out,JSON.stringify(report,null,2)+'\n');let cookie,tabs=[];
async function call(op,args={}){const began=performance.now(),row={op,args};report.calls.push(row);try{const r=await fetch(base+'/api/ui/browser',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:JSON.stringify({op,args}),signal:AbortSignal.timeout(60000)});const value=await r.json();row.http=r.status;row.result=value;if(!r.ok||value.ok===false){const error=Error(JSON.stringify(value));error.value=value;throw error;}return value;}finally{row.ms=performance.now()-began;save();}}
async function open(){const tab=(await call('tab.open',{url:sourceURL,engine:'obscura'})).tabId;tabs.push(tab);await call('tab.grant',{tabId:tab,enabled:true});return tab;}
let encoding='form';
function inputs(query){return {query,queryParam:encoding==='form'?new URLSearchParams([[pairs[0][0],query]]).toString():encodeURIComponent(pairs[0][0])+'='+encodeURIComponent(query)};}
function observedEncoding(value,query){const observation=value?.observation,receipts=value?.receipts||[];
 if(!observation||receipts.length!==learnCall.args.steps.length||!receipts.every(r=>r.verification?.verified===true))return null;
 const url=new URL(observation.url);if(url.searchParams.get(pairs[0][0])!==query)return null;
 const form=new URLSearchParams([[pairs[0][0],query]]).toString(),percent=encodeURIComponent(pairs[0][0])+'='+encodeURIComponent(query);
 if(form===percent)return null;
 const parts=url.search.slice(1).split('&');const matches=[['form',form],['percent',percent]].filter(([,fragment])=>parts.includes(fragment));
 return matches.length===1?{encoding:matches[0][0],actualUrl:observation.url,allEffectsVerified:true}:null;
}
(async()=>{const login=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(!login.ok)throw Error('Owned local session unavailable');cookie=login.headers.get('set-cookie').split(';')[0];
 let tabId=await open();report.admissionAttempts=[];
 try{report.learn=await call('script.learn',{tabId,name:learnCall.args.name,inputs:inputs(firstQuery),steps:learnCall.args.steps,checks:learnCall.args.checks});report.admissionAttempts.push({encoding,result:report.learn});}
 catch(error){report.admissionAttempts.push({encoding,result:error.value,error:error.message});const observed=observedEncoding(error.value,firstQuery);
   if(!observed||observed.encoding===encoding)throw error;
   report.encodingCorrection={...observed,boundary:'All original effects verified; only the independent URL encoding predicate mismatched. Re-admission is on a fresh granted tab, no uncertain effect is replayed.'};encoding=observed.encoding;
   tabId=await open();report.learn=await call('script.learn',{tabId,name:learnCall.args.name,inputs:inputs(firstQuery),steps:learnCall.args.steps,checks:learnCall.args.checks});report.admissionAttempts.push({encoding,result:report.learn});
 }
 const manual=await call('site.manual',{tabId});report.procedure=manual.compiledProcedures.find(p=>p.name===learnCall.args.name);
 if(report.procedure?.inputBindings?.queryParam?.urlQueryParameter!==pairs[0][0])throw Error('Fresh admission did not expose its proved parameter binding');
 const second=await open();report.replay=await call('script.run',{tabId:second,name:learnCall.args.name,inputs:inputs(replayQuery)});
 report.ok=report.learn.compiled&&report.replay.verification?.verified&&report.replay.tokens===0&&report.replay.modelCalls===0;
 if(!report.ok)throw Error('Fresh search compile/replay goal failed');
})().catch(e=>{report.error=e.stack;report.ok=false;process.exitCode=1}).finally(async()=>{for(const tabId of tabs)await call('tab.close',{tabId}).catch(e=>report.closeError=e.message);report.finishedAt=new Date().toISOString();save();console.log(JSON.stringify({ok:report.ok,error:report.error,learnMs:report.learn?.durationMs,replayMs:report.replay?.durationMs}));});
