'use strict';
// Join settled, disjoint fresh-task segments. Never rerun or replace an answer.
const fs=require('node:fs'),crypto=require('node:crypto');
const paths=['scripts/evidence/C2h-frozen36-interrupted.json','scripts/evidence/C2h-frozen36-continuation.json'];
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const segments=paths.map(p=>({path:p,bytes:fs.readFileSync(p)}));
const [first,last]=segments.map(s=>JSON.parse(s.bytes));
if(first.finishedAt||!last.finishedAt||last.fatal||first.port!==last.port||JSON.stringify(first.persistedProfile)!==JSON.stringify(last.persistedProfile)||JSON.stringify(first.sourcesAtStart)!==JSON.stringify(last.sourcesAtStart)||!last.sourcesUnchanged)throw Error('Segments differ or are unfinished');
const tasks=[...first.tasks,...last.tasks],frozen=JSON.parse(fs.readFileSync('scripts/evidence/C2-webvoyager-tasks.json'));
if(tasks.length!==36||new Set(tasks.map(t=>t.id)).size!==36||tasks.some(t=>!t.finishedAt||!t.cleanupFinishedAt)||frozen.tasks.some(t=>!tasks.some(x=>x.id===t.id&&x.goal===t.goal&&x.startUrl===t.startUrl)))throw Error('Exactly36 settled disjoint frozen tasks required');
for(const [p,h]of Object.entries(first.sourcesAtStart))if(hash(fs.readFileSync(p))!==h)throw Error('Executor changed: '+p);
const report={...first,tasks:frozen.tasks.map(t=>tasks.find(x=>x.id===t.id)),calls:[...first.calls,...last.calls],finishedAt:last.finishedAt,sourcesAtFinish:last.sourcesAtFinish,sourcesUnchanged:true,tokens:(first.tokens||0)+(last.tokens||0),modelCalls:(first.modelCalls||0)+(last.modelCalls||0),executionSegments:segments.map(s=>({path:s.path,sha256:hash(s.bytes)})),interruption:{afterCompletedTasks:first.tasks.length,reason:'Shell session disappeared during user steering; no fatal/final journal emitted',allStartedTasksSettled:true,uncertainActionReplays:0,continuation:'Only untouched task IDs; identical executor source and persisted profile'}};
fs.writeFileSync('scripts/evidence/C2h-frozen36.json',JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({tasks:tasks.length,sourcesUnchanged:report.sourcesUnchanged,segments:report.executionSegments}));
