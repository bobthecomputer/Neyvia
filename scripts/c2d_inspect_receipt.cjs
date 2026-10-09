/* Read actual same-ID native failures; never dispatch or replay an effect. */
const fs=require('node:fs');
const [port,id]=process.argv.slice(2);if(port!=='48721'||!id)throw Error('Explicit owned backend48721 and frozen task ID required');
const run=JSON.parse(fs.readFileSync('scripts/evidence/C2d-webvoyager-final.json'));
const task=run.tasks.find(t=>t.id===id);if(!task)throw Error('Task not started');
(async()=>{const login=await fetch(`http://127.0.0.1:${port}/api/auth/local-session`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(!login.ok)throw Error('Owner local session unavailable');const cookie=login.headers.get('set-cookie').split(';')[0];
 const calls=task.calls.map(i=>run.calls[i]),ids=calls.flatMap((row,i)=>row.op==='action'&&calls[i+1]?.op==='wait'?[calls[i+1].args.actionId]:[]).slice(-4);
 for(const actionId of ids){const r=await fetch(`http://127.0.0.1:${port}/api/ui/browser`,{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:JSON.stringify({op:'action.get',args:{actionId}})}),row=await r.json();const receipt={at:new Date().toISOString(),taskId:id,actionId,http:r.status,status:row.status,error:row.error,nativeStatus:row.result?.status,nativeMessage:row.result?.message,verification:row.result?.verification,action:row.op,resultUrl:row.result?.observation?.url,secretsStored:false};fs.appendFileSync('scripts/evidence/C2d-inspected-native-receipts.jsonl',JSON.stringify(receipt)+'\n');console.log(JSON.stringify(receipt));}
})().catch(e=>{console.error(e.message);process.exitCode=1;});
