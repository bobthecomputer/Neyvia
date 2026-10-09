/* Derive requested answer fields from the exact retained live CL observations. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const repo=path.resolve(__dirname,'..');
const hash=x=>crypto.createHash('sha256').update(x).digest('hex');
function extract(task,obs){
 const normalized=obs.text.replace(/\s+/gu,' ').trim();
 const at=normalized.indexOf('Meaning of '+task.word),entry=at>=0?normalized.slice(at):'';
 const pronunciation={};
 for(const m of entry.matchAll(/\b(uk|us)\s+(?:Your browser doesn't support HTML5 audio\s+)?\/([^/]{1,150})\//gu))if(!pronunciation[m[1]])pronunciation[m[1]]='/'+m[2].trim()+'/';
 const match=entry.match(/Add to word list\s+Add to word list\s+(.+?)(?:SMART Vocabulary|More examples|Examples of|Translations of|$)/u);
 const definition=match?match[1].split(/:\s/u)[0].replace(/^[ABC][12]\s+/u,'').trim():null;
 const marker='Examples of '+task.word,begin=entry.indexOf(marker);
 const section=begin>=0?entry.slice(begin+marker.length).replace(new RegExp('^\\s*'+task.word+'\\s+','u'),''):'';
 const examples=section.replace(/This example is from Wikipedia and may be reused under a CC BY-SA license\./gu,'')
   .replace(/From the Cambridge English Corpus|From Wikipedia|From the Hansard archive|From the Cambridge Advanced Learner/gu,' ')
   .split(/(?<=[.!?])\s+/u).map(s=>s.trim())
   .filter(s=>s.toLowerCase().includes(task.word)&&s.split(/\s/u).length>=7&&s.length<=700).slice(0,2);
 const inline=match?.[1].split(/:\s/u)[1];
 if(inline&&examples.length===0){const sentence=inline.match(/^(.+?[.!?])(?:\s|$)/u)?.[1];if(sentence)examples.push(sentence);}
 const actual={definition:typeof definition==='string'&&definition.length>=12&&definition.length<900,
  ipa:!!(pronunciation.uk||pronunciation.us),example:!task.checks.example||examples.length>=(task.id==='Cambridge Dictionary--16'?2:1),
  accents:!task.checks.bothAccents||!!(pronunciation.uk&&pronunciation.us),meanings:!task.checks.meanings};
 return {definition,pronunciation,examples,meaningCount:null,actualChecks:actual,success:Object.values(actual).every(Boolean),
  limitations:[...(task.checks.meanings?['Meaning count requires semantic review; not inferred from duplicate dictionary sections.']:[]),
   ...(task.id==='Cambridge Dictionary--16'?['Two existing public examples extracted; different-context semantics not independently graded.']:[])]};
}
function main(){const reportFile=path.join(repo,'scripts/evidence/C2b-public.json'),report=JSON.parse(fs.readFileSync(reportFile));
 for(const task of report.tasks){if(!task.observationPath)continue;const bytes=fs.readFileSync(path.join(repo,task.observationPath));if(hash(bytes)!==task.observationSha256)throw Error('Observation hash changed '+task.id);Object.assign(task,extract(task,JSON.parse(bytes)));task.scope='Live supplied-entry lookup; extracted definition/IPA/example fields checked. Autonomous discovery and semantic answer grading remain separate.';}
 report.summary.success=report.tasks.filter(t=>t.split==='heldout'&&t.success).length;report.answerCheckVersion=hash(fs.readFileSync(__filename));fs.writeFileSync(reportFile,JSON.stringify(report,null,2)+'\n');
 if(process.argv.includes('--answers-only')){console.log(JSON.stringify({summary:report.summary,boundary:'Answer extraction only; frozen corpus untouched'}));return;}
 const corpus=path.join(repo,'scripts/evidence/C2b-decisions.jsonl'),rows=fs.readFileSync(corpus,'utf8').trim().split('\n').map(JSON.parse);
 for(const row of rows){if(!row.id.endsWith('-decision-9'))continue;const task=report.tasks.find(t=>t.id===row.group),correct=task.success?'Required pronunciation and definition evidence is present.':'Required evidence is missing; this lookup is incomplete.',wrong=task.success?'Required evidence is missing; this lookup is incomplete.':'The lookup succeeded without the required evidence.';row.question.criteria={a:correct,b:wrong};row.gold=row.expected='a';row.expected_check={task:task.id,checks:task.actualChecks};}
 fs.writeFileSync(corpus,rows.map(JSON.stringify).join('\n')+'\n');console.log(JSON.stringify({summary:report.summary,failed:report.tasks.filter(t=>t.split==='heldout'&&!t.success).map(t=>({id:t.id,checks:t.actualChecks})),boundary:'Extracted field checks on retained live observations, not autonomous WebVoyager'}));
}
if(require.main===module)main();module.exports={extract};
