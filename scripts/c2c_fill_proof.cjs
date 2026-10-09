/* Supplemental production fill check; never replaces frozen benchmark attempts. */
const fs=require('node:fs');
const port=Number(process.argv[2]);
if(port!==48725)throw Error('Explicit owned coordinator48725 required');
const file='scripts/evidence/C2c-fill-repair.json',id='Wolfram Alpha--0';
async function command(body){const r=await fetch(`http://127.0.0.1:${port}/command`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const value=await r.json();if(!r.ok)throw Error(JSON.stringify(value));return value;}
(async()=>{
 const obs=await command({op:'observe',id});
 const result=await command({op:'action',id,revision:obs.revision,element:'3',action:'fill',value:'3^71',expect:{path:'/text',contains:'C2c impossible expected saved result'}});
 if(!result.error||!result.error.includes('effect_unconfirmed'))throw Error('False postcondition did not fail');
 const task=JSON.parse(fs.readFileSync(file)).tasks.find(t=>t.id===id);
 const fill=task.trace.find(r=>r.action?.action==='fill'&&r.response?.verification?.verified);
 if(!fill)throw Error('No real verified fill');
 await command({op:'finish',id,status:'failed',reason:'Supplemental repair: input value now verified; compute clears input without rendering result. False explicit postcondition denied. Original first-panel failure retained.'});
 await command({op:'stop'});
 console.log(JSON.stringify({verifiedFill:fill.response.verification,falsePostconditionDenied:true,taskSuccess:false}));
})().catch(e=>{console.error(e);process.exitCode=1;});
