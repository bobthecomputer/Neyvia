/* Exercise the real owner-authenticated browser -> resident CPU decision path. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const repo=path.resolve(__dirname,'..');
process.env.NEYVIA_LAYA_BROWSER_CALIBRATION=path.join(repo,'scripts/evidence/C2b-laya-calibration.json');
const runtime=require('./c2b_public_benchmark.cjs');
const output=path.join(repo,'scripts/evidence/C2b-loop.json');
const report={schema:'neyvia.C2b.loop@1',startedAt:new Date().toISOString(),ports:[48721,48723,48724],checks:[],decisions:[]};
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
function check(label,ok,detail){report.checks.push({label,ok:!!ok,detail});if(!ok)throw Error(label);}
async function health(){const r=await fetch('http://127.0.0.1:48724/v1/health');if(!r.ok)throw Error('Resident unavailable');return r.json();}
async function decision(tabId,field,goal,correct,wrong,extra={}){
 const t=performance.now(),value=await runtime.call('decide',{tabId,question:'calibrated_advisory',context:{goal,decision_profile:'public_observed_fields@1',advisory_field:field,options:[{id:'a',description:correct},{id:'b',description:wrong}],...extra}});
 report.decisions.push({field,goal,ms:performance.now()-t,response:value});return value;
}
async function main(){
 report.healthBefore=await health();await runtime.start();
 for(const url of ['https://docs.python.org/3/library/json.html','https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/JSON']){
  const tab=(await runtime.call('tab.open',{url,engine:'obscura'})).tabId;
  const obs=await runtime.call('observe',{tabId:tab});
  const result=await decision(tab,'title','Choose the observed page topic.',obs.title,'An unrelated password reset page');
  check('fresh title accepted '+new URL(url).hostname,result.accepted_decision==='a'&&result.decision_policy?.policy==='answer+postcheck'&&result.decision_policy.postcheck_passed&&result.selected_action===null,result.decision_policy);
  const blocked=await decision(tab,'title','Choose an unsupported page judgment.',obs.title,'An unrelated password reset page');
  check('unsupported instruction escalates '+new URL(url).hostname,!blocked.accepted_decision&&blocked.decision_policy?.policy==='escalate'&&!blocked.selected_action,blocked.decision_policy);
  const falseOptions=await decision(tab,'title','Choose the observed page topic.','An unrelated password reset page','A nonexistent private payment form');
  check('incorrect candidate fails fresh-field postcheck '+new URL(url).hostname,!falseOptions.accepted_decision&&falseOptions.decision_policy?.policy==='escalate'&&falseOptions.decision_policy.postcheck_passed===false&&!falseOptions.selected_action,falseOptions.decision_policy);
  const controls=obs.elements.filter(e=>e.enabled&&!e.secret&&e.actions.includes('click'));
  if(controls.length>=2){const action=await runtime.call('decide',{tabId:tab,question:'grounded_action',context:{goal:'Activate the '+controls[0].role+' named "'+controls[0].name+'".',decision_profile:'public_document_controls@1',options:controls.slice(0,2).map((e,i)=>({id:i?'b':'a',description:'Click the '+e.role+' "'+e.name+'".',args:{element:e.id,action:'click'}}))}});
   report.decisions.push({field:'action',response:action});check('failed action confidence gate refuses '+new URL(url).hostname,!action.selected_action&&action.browser_policy?.policy==='escalate',action.browser_policy);}
  await runtime.call('tab.close',{tabId:tab});
 }
 report.healthAfter=await health();check('same loaded CPU identity',JSON.stringify(report.healthBefore.identity)===JSON.stringify(report.healthAfter.identity),{before:report.healthBefore,after:report.healthAfter});
 report.sourceHashes=Object.fromEntries(['src/grant_agent/laya_client/browser_client.py','src/grant_agent/laya_client/calibration.py','src/grant_agent/laya_client/fast_cpu.py','src/grant_agent/laya_service.py','scripts/evidence/C2b-laya-calibration.json'].map(p=>[p,sha(path.join(repo,p))]));
}
main().catch(e=>{report.error=String(e.stack);process.exitCode=1;}).finally(async()=>{await runtime.stop();report.finishedAt=new Date().toISOString();report.calls=runtime.report.calls;fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({checks:report.checks,error:report.error}));});
