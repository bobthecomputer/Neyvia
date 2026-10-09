'use strict';
// Separate post-run evaluator; executor status and internal done judges are withheld.
const fs=require('node:fs'),crypto=require('node:crypto'),path=require('node:path');
const {decide}=require('./browser_luna.cjs'),{access}=require('./browser_task_cascade.cjs');
const [runPath,out]=process.argv.slice(2),sha=b=>crypto.createHash('sha256').update(b).digest('hex'),norm=s=>String(s??'').replace(/\s+/gu,' ').trim();
if(!runPath||!out||fs.existsSync(out)&&!process.argv.includes('--resume'))throw Error('Finished run and fresh review required');
const bytes=fs.readFileSync(runPath),run=JSON.parse(bytes);if(!run.finishedAt||run.tasks.length!==36)throw Error('Full finished frozen36 required');
const requirements=JSON.parse(fs.readFileSync('config/browser_goal_clauses.json')),refs=JSON.parse(fs.readFileSync('scripts/evidence/C2-webvoyager-references.json'));
const review=fs.existsSync(out)?JSON.parse(fs.readFileSync(out)):{schema:'neyvia.C2h.separate-review@1',runSha256:sha(bytes),graderIdentity:'Separate typed gpt-6-luna post-run evaluator; Codex integration review',method:'Adapted browser-use key-criteria judgment without executor status/stages, exact answer and observation hashes, separate evaluator calls. No human grader or separate Codex agent is claimed.',reviews:{},receipts:[]};
if(review.runSha256!==sha(bytes))throw Error('Run changed');const save=()=>fs.writeFileSync(out,JSON.stringify(review,null,2)+'\n');
function locate(e,docs){const d=docs[e.document];if(!d)return null;const v=d.value[e.field],structured=typeof v==='object',text=structured?JSON.stringify(v):norm(v),quote=structured?e.quote:norm(e.quote);return quote&&text.includes(quote)?{path:d.ref.path,field:e.field,quote:e.quote}:null;}
(async()=>{for(const task of run.tasks){if(review.reviews[task.id])continue;
 const docs=task.observations.map(ref=>{const b=fs.readFileSync(ref.path);if(sha(b)!==ref.sha256)throw Error('Observation changed');return{ref,value:JSON.parse(b)}});
 const wall=docs.findLast(d=>access(d.value));let outcome,reason,clauses;
 if(task.ownerHandoff||wall){outcome='needs_owner';reason='Fresh observed access wall; owner action required, never a pass';clauses=requirements[task.id].map(requirement=>({requirement,met:false,evidence:[]}));}
 else if(!task.answer){outcome='failed';reason='No answer returned by the executor';clauses=requirements[task.id].map(requirement=>({requirement,met:false,evidence:[]}));}
 else {const unique=[...new Map(docs.map((d,index)=>[sha(JSON.stringify([d.value.url,d.value.text,d.value.tables,d.value.elements])),{...d,index}])).values()];
  const selected=unique.slice(-16),r=await decide({mode:'review',goal:task.goal,requirements:requirements[task.id],answer:task.answer,referenceInterpretation:refs.answers[task.id],asOf:run.startedAt,documents:selected.map(d=>({index:d.index,url:d.value.url,title:d.value.title,text:d.value.text,tables:d.value.tables,elements:d.value.elements,truncated:d.value.truncated}))},{directory:path.resolve('.agent_control/C2h/post-run-review',task.id.replace(/[^a-z0-9-]/gi,'_'))});
  review.receipts.push({taskId:task.id,...r.receipt});outcome=r.decision.outcome;reason=r.decision.reason;
  clauses=requirements[task.id].map(requirement=>{const rows=r.decision.clauses.filter(c=>c.requirement===requirement),c=rows[0],evidence=(c?.evidence||[]).map(e=>locate(e,docs)).filter(Boolean);return{requirement,met:rows.length===1&&c.met&&evidence.length===c.evidence.length&&evidence.length>0,evidence};});if(outcome==='passed'&&!clauses.every(c=>c.met)){outcome='failed';reason+=' Exact source-binding or all-clause coverage failed.';}}
 review.reviews[task.id]={outcome,reason,clauses,evidenceCoverageComplete:outcome==='passed',answerSha256:sha(JSON.stringify({answer:task.answer??null,status:task.status??null,reason:task.reason??null})),ownerBoundaryEvidence:wall?[{path:wall.ref.path,field:'title',quote:wall.value.title}]:[]};save();console.log(JSON.stringify({id:task.id,outcome,reason:reason.slice(0,150)}));
 }review.finishedAt=new Date().toISOString();review.tokens=review.receipts.reduce((sum,r)=>sum+(r.usage?.input_tokens||0)+(r.usage?.output_tokens||0),0);save();})().catch(e=>{review.error=e.stack;save();console.error(e.message);process.exitCode=1;});
