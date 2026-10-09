/* Fresh public observations, frozen before evaluating a changed representation. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const runtime=require('./c2b_public_benchmark.cjs'),repo=path.resolve(__dirname,'..');
const urls=[
 'https://en.wikipedia.org/wiki/HTTP','https://en.wikipedia.org/wiki/Web_browser','https://en.wikipedia.org/wiki/Computer_keyboard','https://en.wikipedia.org/wiki/Periodic_table',
 'https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/table','https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/input','https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/button','https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe',
 ...['json','pathlib','asyncio','argparse','csv','collections','datetime','re','os','urllib.request','threading','logging','subprocess','statistics','heapq','dataclasses','html.parser','typing','itertools'].map(topic=>'https://docs.python.org/3/library/'+topic+'.html'),
 'https://doc.rust-lang.org/book/ch03-00-common-programming-concepts.html','https://doc.rust-lang.org/book/ch04-00-understanding-ownership.html',
 'https://www.w3.org/WAI/tutorials/forms/','https://www.w3.org/WAI/tutorials/tables/'
];
const report={schema:'neyvia.C2b.fresh-action-corpus@1',startedAt:new Date().toISOString(),root:path.relative(repo,runtime.root),pages:[],boundary:'Actual public DOM observations with checked candidate-selection labels; an annotated decision corpus, not completed web tasks'},rows=[];
const hash=x=>crypto.createHash('sha256').update(x).digest('hex');
const save=()=>{fs.writeFileSync(path.join(repo,'scripts/evidence/C2b-action-capture.json'),JSON.stringify(report,null,2)+'\n');fs.writeFileSync(path.join(repo,'scripts/evidence/C2b-action-decisions.jsonl'),rows.map(JSON.stringify).join('\n')+'\n');};
async function main(){await runtime.start();for(let pageIndex=0;pageIndex<urls.length;pageIndex++){
 const url=urls[pageIndex],id='fresh-page-'+pageIndex;let tabId;const t=performance.now(),entry={id,url};
 try{tabId=(await runtime.call('tab.open',{url,engine:'obscura'})).tabId;const obs=await runtime.call('observe',{tabId});const observationPath='scripts/evidence/C2b-action-observations/'+id+'.json',bytes=JSON.stringify(obs,null,2)+'\n';fs.mkdirSync(path.dirname(path.join(repo,observationPath)),{recursive:true});fs.writeFileSync(path.join(repo,observationPath),bytes);
 const safe=obs.elements.filter(e=>e.enabled&&!e.secret&&e.actions.includes('click')&&e.name.length>=2&&e.name.length<=120);
 const unique=safe.filter(e=>safe.filter(o=>o.role===e.role&&o.name===e.name).length===1);
 if(unique.length<12)throw Error('Fewer than12 distinct observed safe controls');
 const selected=Array.from({length:12},(_,i)=>unique[Math.floor(i*unique.length/12)]);
 for(let i=0;i<12;i++){const target=selected[i],other=selected[(i+1)%12],goal=`Activate the ${target.role} named "${target.name}".`,correct=`Click the ${target.role} "${target.name}".`,wrong=`Click the ${other.role} "${other.name}".`,swap=(pageIndex+i)%2===0;
 const criteria=swap?{a:wrong,b:correct}:{a:correct,b:wrong};rows.push({id:id+'-action-'+i,split:'heldout',domain:'browser',family:'grounded_action',decision_profile:'public_document_controls@1',group:id,provenance:{run_id:path.basename(runtime.root),url:obs.url,observed_at:new Date().toISOString(),observation_path:observationPath,observation_sha256:hash(bytes)},state:{},goal,question:{type:'choice',instructions:goal,criteria,thresholds:{answer:.5}},gold:swap?'b':'a',expected:swap?'b':'a',expected_check:{element:target.id,alternative:other.id,action:'click',name:target.name,role:target.role}});}
 entry.observationPath=observationPath;entry.observationSha256=hash(bytes);entry.decisions=12;entry.ok=true;
 }catch(error){entry.ok=false;entry.error=String(error.stack);}finally{entry.ms=performance.now()-t;report.pages.push(entry);save();if(tabId)try{await runtime.call('tab.close',{tabId});}catch{}}console.log(JSON.stringify({id,ok:entry.ok,ms:entry.ms,decisions:rows.length,error:entry.error?.slice(0,90)}));
 }report.finishedAt=new Date().toISOString();report.heldoutDecisions=rows.length;}
main().catch(error=>{report.fatal=String(error.stack);process.exitCode=1;}).finally(async()=>{await runtime.stop();save();console.log(JSON.stringify({heldout:rows.length,pages:report.pages.length,ok:report.pages.filter(p=>p.ok).length}));});
