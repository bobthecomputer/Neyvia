'use strict';
const fs=require('node:fs'),http=require('node:http'),assert=require('node:assert/strict');
const [portText,fixtureText,out]=process.argv.slice(2),port=Number(portText),fixture=Number(fixtureText);
if(!out||fs.existsSync(out)||[port,fixture].some(p=>p<48721||p>48739)||port===fixture)throw Error('Fresh output and distinct assigned ports required');
const report={startedAt:new Date().toISOString(),boundary:'Actual registered task with an actual delayed DOM effect; no public task score',calls:[]};
const site=http.createServer((q,r)=>{r.setHeader('Content-Type','text/html');r.end('<!doctype html><title>Delayed effect</title><button onclick="window.reveals=(window.reveals||0)+1;setTimeout(()=>document.querySelector(\'output\').textContent=\'The result is indigo\',9500)">Reveal result</button><output>Result pending</output>');});
let cookie,tab;
async function call(op,args={}){const start=performance.now(),r=await fetch(`http://127.0.0.1:${port}/api/ui/browser`,{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:JSON.stringify({op,args}),signal:AbortSignal.timeout(300000)}),v=await r.json();report.calls.push({op,http:r.status,ms:performance.now()-start,response:v});if(!r.ok)throw Error(JSON.stringify(v));return v;}
(async()=>{await new Promise(r=>site.listen(fixture,'127.0.0.1',r));const s=await fetch(`http://127.0.0.1:${port}/api/auth/local-session`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});cookie=s.headers.get('set-cookie').split(';')[0];
 tab=(await call('tab.open',{url:`http://127.0.0.1:${fixture}`,engine:'obscura'})).tabId;await call('tab.grant',{tabId:tab,enabled:true});
 const task=await call('task.run',{tabId:tab,goal:'Click Reveal result once, observe until the result appears and return its color.',requirements:['Return the revealed result color'],checks:[{path:'/text',contains:'The result is indigo'}],allowModel:true,maxActions:2,maxModelCalls:6});
 assert.equal(task.status,'done');assert.equal(task.steps,1);assert.match(task.answer,/indigo/i);assert.ok(task.stages.some(s=>s.stage==='read-only-recovery'&&s.actionReplays===0));report.ok=true;
})().catch(e=>{report.ok=false;report.error=e.stack;process.exitCode=1;}).finally(async()=>{if(tab)await call('tab.close',{tabId:tab}).catch(e=>report.closeError=e.message);site.close();report.finishedAt=new Date().toISOString();fs.writeFileSync(out,JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({ok:report.ok,error:report.error}));});
