/* Small CL operator view. Full observations remain in hashed evidence. */
const fs=require('node:fs');
const reportPath=process.env.C2C_RUN_REPORT||'scripts/evidence/C2c-webvoyager.json';
const [port,op,id,target,value]=process.argv.slice(2);
if(!/^4872[1-6]$/.test(port))throw Error('Explicit coordinator port required');
let body={op,id};
if(op==='finish'){
 const task=JSON.parse(fs.readFileSync(reportPath,'utf8')).tasks.find(t=>t.id===id);
 body={op,id,status:target,...(target==='answered'?{answer:value,evidence:[{url:task.lastObservation.url,observation:task.observations.at(-1),passage:task.lastObservation.text.slice(0,12000)}]}:{reason:value,evidence:task?.lastObservation?[{url:task.lastObservation.url,passage:task.lastObservation.text.slice(0,1800)}]:[]})};
}
if(['click','fill','select','scroll'].includes(op)){
 const task=JSON.parse(fs.readFileSync(reportPath,'utf8')).tasks.find(t=>t.id===id);
 if(!task?.lastObservation)throw Error('Need fresh observed state');
 body={op:'action',id,revision:task.lastObservation.revision,element:target,action:op,...(value===undefined?{}:{value})};
}
fetch(`http://127.0.0.1:${port}/command`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(90000)}).then(async r=>{
 const result=await r.json();const obs=result.observation||result;
 if(obs.elements){const regex=process.env.C2C_VIEW_RE?new RegExp(process.env.C2C_VIEW_RE,'i'):null;obs.elements=obs.elements.filter(e=>!regex||regex.test(e.role+' '+e.name+' '+e.value)).slice(0,100).map(e=>[e.id,e.role,e.name,e.value]);obs.text=obs.text?.slice(0,Number(process.env.C2C_VIEW_TEXT||7000));}
 console.log(JSON.stringify(result));if(!r.ok)process.exitCode=1;
}).catch(e=>{console.error(e);process.exitCode=1;});
