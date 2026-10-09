'use strict';
// Real typed Luna judge calls plus bounded checks of the adapted stall logic.
const fs=require('node:fs'),assert=require('node:assert/strict'),path=require('node:path');
const {decide}=require('./browser_luna.cjs');
const {LoopGuidance}=require('./browser_completion.cjs');
const out=process.argv[2];if(!out||fs.existsSync(out))throw Error('Fresh receipt required');
const report={schema:'neyvia.C2h.planner-proof@1',startedAt:new Date().toISOString(),checks:[]};
const save=()=>fs.writeFileSync(out,JSON.stringify(report,null,2)+'\n');
const cases=[
 {id:'already-complete',goal:'Return the names and prices of both listed products.',requirements:['Both product names','Both prices'],answer:'Birch costs $12; Cedar costs $18.',text:'All products (2 total): Birch $12. Cedar $18.',expected:true},
 {id:'partial-answer',goal:'Return the names and prices of both listed products.',requirements:['Both product names','Both prices'],answer:'Birch costs $12.',text:'All products (2 total): Birch $12. Cedar $18.',expected:false},
 {id:'supported-negative',goal:'List releases from October 1 through October 5, 2026.',requirements:['Complete filtered date-window coverage'],answer:'No releases are in the requested window, October 1 through October 5, 2026.',text:'Filters applied: From 2026-10-01 To 2026-10-05. Results: 0. All results displayed.',expected:true},
 {id:'unsupported-negative',goal:'List releases from October 1 through October 5, 2026.',requirements:['Complete filtered date-window coverage'],answer:'No releases are in the requested window.',text:'Release dated September 30, 2026. More results: next page.',expected:false},
 {id:'owner-wall',goal:'Read the product price.',requirements:['Observed product price'],answer:'Task complete.',text:'Verify you are human. CAPTCHA.',expected:false,captcha:true}
];
(async()=>{try{
 const selected=process.argv.includes('--finish-only')?[]:cases;
 for(const c of selected){const r=await decide({mode:'judge',goal:c.goal,requirements:c.requirements,answer:c.answer,documents:[{url:'http://127.0.0.1:48732/evidence',title:'Disposable judge evidence',text:c.text,truncated:false}],previousStages:[]},{directory:path.resolve('.agent_control/C2h/planner-proof',c.id)});const passed=r.decision.verdict===c.expected&&(!c.captcha||r.decision.reached_captcha);report.checks.push({id:c.id,passed,decision:r.decision,receipt:r.receipt});save();}
 for(const c of selected.slice(0,2)){const r=await decide({mode:'review',goal:c.goal,requirements:c.requirements,answer:c.answer,documents:[{index:5,url:'http://127.0.0.1:48732/evidence',title:'Review evidence',text:c.text,truncated:false}]},{directory:path.resolve('.agent_control/C2h/planner-proof','review-'+c.id)});const passed=r.decision.outcome===(c.expected?'passed':'failed')&&(!c.expected||r.decision.clauses.length===2&&r.decision.clauses.every(row=>row.met&&row.evidence.every(e=>e.document===5&&e.field==='text'&&c.text.includes(e.quote))));report.checks.push({id:'separate-review-'+c.id,passed,decision:r.decision,receipt:r.receipt});save();}
 const acquired=JSON.parse(fs.readFileSync('scripts/evidence/C2h-admitted-recovery-finish-proof.json')).calls.find(c=>c.op==='task.run').response;
 const finished=await decide({finishOnly:true,goal:acquired.goal,requirements:['Return the revealed result color'],current:acquired.observation,documents:[{...acquired.observation,index:0}],previousStages:acquired.stages},{directory:path.resolve('.agent_control/C2h/planner-proof','finish-only')});
 report.checks.push({id:'force-answer-without-new-action',passed:finished.decision.status==='done'&&finished.decision.action.kind==='none'&&/indigo/i.test(finished.decision.answer),decision:finished.decision,receipt:finished.receipt});save();
 const loop=new LoopGuidance();for(let i=0;i<8;i++){loop.page({url:'http://127.0.0.1:48732/stalled',text:'unchanged',elements:[{id:'a',role:'button',name:'Go'}]});loop.action({kind:'click',element:'a'},{elements:[{id:'a',role:'button',name:'Go'}]});loop.result(false);}const nudge=loop.nudge();assert.match(nudge,/Replan/);assert.match(nudge,/change approach/);assert.match(nudge,/unchanged/);loop.result(true);assert.doesNotMatch(loop.nudge(),/consecutive failed/);report.checks.push({id:'stall-replan-loop-nudge',passed:true,nudge});
 report.tokens=report.checks.reduce((sum,c)=>sum+(c.receipt?.usage?.input_tokens||0)+(c.receipt?.usage?.output_tokens||0),0);report.passed=report.checks.every(c=>c.passed);report.finishedAt=new Date().toISOString();save();console.log(JSON.stringify({passed:report.passed,checks:report.checks.map(c=>({id:c.id,passed:c.passed})),tokens:report.tokens}));if(!report.passed)process.exitCode=1;
 }catch(e){report.error=e.stack;save();throw e;}})();
