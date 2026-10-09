/* Real production Obscura checks for the interrupted DOM changes. */
const fs=require('node:fs'),http=require('node:http');
const runtime=require('./c2b_public_benchmark.cjs');
const receipt={schema:'neyvia.C2d.dom-recovery@1',startedAt:new Date().toISOString(),checks:[]};
let server,tabId;
const html=`<!doctype html><title>C2d recovery</title><form onsubmit="event.preventDefault();document.getElementById('result').textContent='Submitted: '+document.getElementById('query').value"><label>Search<input id="query" name="q" placeholder="Search records" type="search"></label><input id="locked" readonly value="keeper"><fieldset disabled><input id="disabled" value="keeper"></fieldset><select id="sort"><option value="new">Newest</option><optgroup disabled><option value="bad">Unavailable</option></optgroup></select><button>Search</button></form><a href="/records">Records</a><p id="result">Ready</p>`;
function check(name,ok){receipt.checks.push({name,ok});if(!ok)throw Error(name);}
async function main(){
 await runtime.start();server=http.createServer((q,r)=>{r.setHeader('Content-Type','text/html');r.end(html);});await new Promise(r=>server.listen(48722,'127.0.0.1',r));
 tabId=(await runtime.call('tab.open',{url:'http://127.0.0.1:48722/',engine:'obscura'})).tabId;await runtime.call('tab.grant',{tabId,enabled:true});
 let obs=await runtime.call('observe',{tabId});const query=obs.elements.find(e=>e.inputName==='q');
 check('search/form semantics observed',query?.type==='search'&&query.placeholder==='Search records'&&query.form?.method==='get'&&query.actions.includes('submit'));
 check('readonly fill denied',obs.elements.find(e=>e.readOnly)?.actions.includes('fill')===false);
 check('disabled fieldset inherited',obs.elements.some(e=>e.value==='keeper'&&!e.enabled&&e.actions.length===0));
 check('select disabled option observed',obs.elements.find(e=>e.role==='combobox')?.options.some(o=>o.value==='bad'&&!o.enabled));
 check('observed link destination',obs.elements.find(e=>e.name==='Records')?.href==='http://127.0.0.1:48722/records');
 // Recovery submit is checked in the shared executor even before schema wiring.
 let result=await runtime.call('action',{tabId,revision:obs.revision,element:query.id,action:'fill',value:'recovery',expect:{path:'/elements/'+obs.elements.indexOf(query)+'/value',equals:'recovery'}});check('fill actual value verified',result.verification.verified);
 obs=result.observation;const current=obs.elements.find(e=>e.inputName==='q');result=await runtime.call('action',{tabId,revision:obs.revision,element:current.id,action:'submit',expect:{path:'/text',contains:'Submitted: recovery'}});check('form submit actual effect verified',result.verification.verified);
 receipt.final={url:result.observation.url,text:result.observation.text,verification:result.verification};
}
main().catch(e=>{receipt.error=e.stack;process.exitCode=1;}).finally(async()=>{if(tabId)try{await runtime.call('tab.close',{tabId});}catch{}if(server)await new Promise(r=>server.close(r));await runtime.stop();receipt.finishedAt=new Date().toISOString();fs.writeFileSync('scripts/evidence/C2d-dom-recovery.json',JSON.stringify(receipt,null,2)+'\n');console.log(JSON.stringify(receipt));});
