/* Refresh and bind a preplanned semantic batch without a model round trip. */
const [port,id,input]=process.argv.slice(2);if(port!=='48722')throw Error('Explicit C2d coordinator port required');
const fs=require('node:fs'),steps=JSON.parse(fs.readFileSync(input,'utf8'));
async function call(body){const r=await fetch(`http://127.0.0.1:${port}/command`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(90000)});const v=await r.json();if(!r.ok)throw Error(JSON.stringify(v));return v;}
(async()=>{const obs=await call({op:'observe',id});const result=await call({op:'batch',id,revision:obs.revision,steps});if(result.observation){const o=result.observation;o.elements=o.elements.filter(e=>e.actions.some(a=>a!=='scroll')).slice(0,Number(process.env.C2D_CONTROLS||8));o.text=o.text.slice(0,Number(process.env.C2D_TEXT||14000));}console.log(JSON.stringify(result));})().catch(e=>{console.error(e);process.exitCode=1;});
