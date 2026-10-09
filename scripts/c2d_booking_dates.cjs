/* Operator plan uses only live named controls; no guessed routes or answers. */
const fs=require('node:fs');const [port,id,destination,arrival,departure]=process.argv.slice(2);
if(port!=='48722'||!/^Booking--[012]$/.test(id)||!destination||!/^20\d\d-\d\d-\d\d$/.test(arrival)||!/^20\d\d-\d\d-\d\d$/.test(departure))throw Error('Supply explicit48722, frozen Booking task, destination and ISO dates');
const receipts=[];const out=`scripts/evidence/C2d-booking-dates-${id}.json`;
async function call(body){const r=await fetch(`http://127.0.0.1:${port}/command`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,...body}),signal:AbortSignal.timeout(90000)});const v=await r.json();if(!r.ok)throw Error(JSON.stringify(v));return v;}
const target=e=>Object.fromEntries(['role','name','inputName','frame'].filter(k=>k in e).map(k=>[k,e[k]]));
async function batch(steps){const before=await call({op:'observe'}),r=await call({op:'batch',revision:before.revision,steps});receipts.push({at:new Date().toISOString(),steps,ok:r.ok,error:r.error,receipts:r.receipts});if(!r.ok)throw Error(JSON.stringify({error:r.error,receipts:r.receipts}));return r.observation;}
const dayLabel=s=>new Intl.DateTimeFormat('fr-FR',{weekday:'long',day:'numeric',month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(s+'T12:00:00Z'));
const unique=(o,test)=>{const rows=o.elements.filter(e=>e.enabled&&!e.secret&&test(e));if(rows.length!==1)throw Error('Expected exactly one actual enabled control, got'+rows.length);return rows[0];};
(async()=>{let o=await call({op:'observe'});const dismiss=o.elements.find(e=>e.enabled&&e.role==='button'&&e.name==='Ignorer les infos relatives à la connexion');if(dismiss)o=await batch([{target:target(dismiss),action:'click'}]);
 const field=unique(o,e=>e.actions.includes('fill')&&e.inputName==='ss');o=await batch([{target:target(field),action:'fill',value:destination}]);
 const calendar=unique(o,e=>e.actions.includes('click')&&/^Choisir des dates/.test(e.name));o=await batch([{target:target(calendar),action:'click'}]);
 for(let i=0;i<5&&!o.elements.some(e=>e.name===dayLabel(arrival)&&e.enabled&&e.actions.includes('click'));i++){const next=unique(o,e=>e.actions.includes('click')&&e.name==='Mois suivant');o=await batch([{target:target(next),action:'click'}]);}
 const dateControl=(observation,date)=>{const name=dayLabel(date),role=observation.elements.some(e=>e.role==='checkbox'&&e.name===name&&e.enabled)?'checkbox':'gridcell';return unique(observation,e=>e.role===role&&e.name===name&&e.actions.includes('click'));};
 const checkin=dateControl(o,arrival);o=await batch([{target:target(checkin),action:'click'}]);
 const checkout=dateControl(o,departure);o=await batch([{target:target(checkout),action:'click'}]);
 o=await call({op:'observe'});const r={schema:'neyvia.C2d.booking-date-plan@1',id,destination,arrival,departure,receipts,finalRevision:o.revision,url:o.url,text:o.text.slice(0,1700),controls:o.elements.filter(e=>e.actions.some(a=>a!=='scroll')&&/Indiquez|Choisir|personnes|Rechercher/.test(e.name)),sourceBoundary:'Actual observed controls; date selection is not availability, deals, occupancy or price proof'};fs.writeFileSync(out,JSON.stringify(r,null,2)+'\n');console.log(JSON.stringify(r));
})().catch(e=>{fs.writeFileSync(out,JSON.stringify({id,destination,arrival,departure,receipts,error:e.message},null,2)+'\n');console.error(e.message);process.exitCode=1;});
