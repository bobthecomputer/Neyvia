/* Freeze public goals before acquisition. The executor never receives references. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const repo=path.resolve(__dirname,'..'),scratch=path.join(repo,'.agent_control/C2c');
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const source=fs.readFileSync(path.join(scratch,'WebVoyager_data.jsonl'));
const referencesBytes=fs.readFileSync(path.join(scratch,'reference_answer.json'));
const rows=source.toString('utf8').trim().split('\n').map(JSON.parse),refs=JSON.parse(referencesBytes);
const sites=['Allrecipes','Apple','ArXiv','BBC News','Booking','Cambridge Dictionary','Coursera','ESPN','GitHub','Google Search','Huggingface','Wolfram Alpha'];
const rubric={
  success:'All requested facts and constraints must be answered from captured live page evidence. Page load, a search result title, and partial answers alone fail. No answer URL or reference is supplied to the executor.',
  navigation:'Start at the exact public start URL. Use observed controls/links, including search, filtering, pagination and tables when the goal requires them. Each submitted action binds a fresh revision. Record the full trace.',
  reference:'Grade against the upstream reference when present. Possible answers are examples, not exhaustive sets. For historical price/ranking/latest references, use the original constraints with captured current evidence and record the discrepancy; never invent an updated reference.',
  fallback:'If no applicable reference exists, require every clause of the goal, source URL and quoted supporting page passages; latest requires a date/order check, counts require the complete filtered set, comparisons require both values, summaries require factual support for every substantive claim.',
  skip:'Only an observed login, CAPTCHA/bot/access wall, or task requiring unauthorized account/API access permits skipped. Record page URL, evidence and reason, never bypass. Engine/parser/network failure and missing controls are failed, not skipped.',
  dates:'Use the next occurrence of undated future booking dates after the frozen UTC date; explicitly report the chosen year. Relative dates use each arm run UTC date and must be stated in the answer.',
  metrics:'Report attempted/success/failed/skipped, both success denominators, semantic action steps and total API calls, end-to-end task p50/p95, page-to-CL and action-to-verified p50/p95, provider cost/task. Unmeasured operator and local compute cost stays null.',
  grading:'A separate grader sees the reference and trace after the executor answer is frozen. Every pass has per-clause evidence, every fail identifies missing clauses. Unreviewed answers remain ungraded and cannot count as success.'
};
const tasks=[],answers={};
for(const site of sites){for(const index of site==='Huggingface'?[0,2,3]:[0,1,2]){
 const row=rows.find(r=>r.id===site+'--'+index);if(!row)throw Error('Missing public task');
 const ref=refs[site]?.answers.find(r=>r.id===index);
 tasks.push({id:row.id,site:row.web_name,startUrl:row.web,goal:row.ques,rubric:{requirements:row.ques,referenceAvailable:!!ref,referenceType:ref?.type||null,referencePath:'C2-webvoyager-references.json#'+row.id,allRequirements:true},maxActions:20});
 answers[row.id]={...ref,notice:refs[site]?.notice||'',applicability:'Static facts compare semantically; live/possible facts use current evidence satisfying every goal constraint.'};
}}
const evidence=path.join(repo,'scripts/evidence'),target=path.join(evidence,'C2-webvoyager-tasks.json');
if(fs.existsSync(target))throw Error('Task list already frozen; do not overwrite');
const set={schema:'neyvia.C2c.webvoyager-tasks@1',frozenAt:new Date().toISOString(),source:'https://github.com/MinorJerry/WebVoyager',sourceData:'https://raw.githubusercontent.com/MinorJerry/WebVoyager/main/data/WebVoyager_data.jsonl',sourceSha256:hash(source),referenceSource:'https://raw.githubusercontent.com/MinorJerry/WebVoyager/main/data/reference_answer.json',referenceSha256:hash(referencesBytes),selection:'First three public tasks per listed site in dataset order, except HF--1 requires account/API generation so HF--3 replaces it; no selection based on run success.',adaptations:['No supplied answer URLs','Undated future booking dates use next occurrence; all other goals unchanged'],stealth:false,rubric,tasks};
fs.writeFileSync(target,JSON.stringify(set,null,2)+'\n');
fs.writeFileSync(path.join(evidence,'C2-webvoyager-references.json'),JSON.stringify({schema:'neyvia.C2c.grader-references@1',executorAccess:false,sourceSha256:hash(referencesBytes),answers},null,2)+'\n');
console.log(JSON.stringify({tasks:tasks.length,sites:sites.length,path:target,sha256:hash(fs.readFileSync(target))}));
