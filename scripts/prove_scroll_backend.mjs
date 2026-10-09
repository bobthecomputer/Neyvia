import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
const repo=path.resolve(import.meta.dirname,'..');
const root=path.join(repo,'.agent_control/a3b/runtime');
const base='http://127.0.0.1:48591';
const output=path.join(repo,'scripts/evidence/A3B-http.json');
const resume=process.argv.includes('--resume');
const requestId=process.argv.includes('--job')?process.argv[process.argv.indexOf('--job')+1]:'a3b-learning-cold';
const proof=resume&&fs.existsSync(output)?JSON.parse(fs.readFileSync(output)): {schema:'neyvia.A3B.http.v1',at:new Date().toISOString(),root,base,checks:[]};
let cookie='';
function save(){fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(proof,null,2));}
function record(name,data=true){proof.checks.push({name,data});save();console.log(name);}
async function request(route,body,raw=false){const response=await fetch(base+route,{method:body===undefined?'GET':'POST',headers:{'content-type':'application/json',cookie},...(body===undefined?{}:{body:JSON.stringify(body)})});const data=await response.json();if(raw)return{status:response.status,data};assert.ok(response.ok,JSON.stringify(data));assert.notEqual(data.ok,false,JSON.stringify(data));return data.data??data;}
async function tool(op,args){const result=await request('/api/ui/tools/call',{tool:'neyvia.scroll.'+op,arguments:args});assert.notEqual(result.ok,false,JSON.stringify(result));return result.result??result;}
async function main(){
 const denied=await request('/api/ui/scroll/state',undefined,true);assert.equal(denied.status,401);record('unauthenticated state refused');
 const login=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'content-type':'application/json'},body:'{}'});assert.ok(login.ok);cookie=login.headers.getSetCookie().map(x=>x.split(';')[0]).join(';');
 const tools=await request('/api/ui/tools');for(const op of ['import','concepts','generate','job','validate','review','pack','preview','send','stats','state'])assert.ok(tools.tools.some(x=>x.name==='neyvia.scroll.'+op));record('11 native scroll tools discovered');
 const pack='learning-notes';
 if(!resume){
   proof.import=await tool('import',{paths:[path.join(root,'study-notes.md')],packId:pack,title:'Retrieval and spaced learning',subject:'learning'});record('real repository research notes imported and hashed',proof.import.pack.sources);
   proof.graph=await tool('concepts',{pack});record('real Luna confirmed graph',proof.graph);
   proof.started=await tool('generate',{pack,requestId});record('durable real generation started',proof.started);
 }
 const first=await tool('generate',{pack,requestId});
 const replay=await tool('generate',{pack,requestId});assert.ok(replay.replayed);record('request retry replayed same job',replay);
 const collision=await request('/api/ui/scroll',{operation:'generate',pack,scope:{concepts:['nonexistent']},requestId},true);assert.equal(collision.status,400);record('request ID argument collision refused');
 let job;const until=Date.now()+1200000;
 while(Date.now()<until){job=(await tool('job',{requestId})).job;proof.job=job;save();if(['completed','failed'].includes(job.state))break;await new Promise(r=>setTimeout(r,1500));}
 assert.equal(job?.state,'completed',job?.error??'generation did not finish');record('real generation completed',job);
 const check=await tool('validate',{pack});proof.validation=check;save();assert.ok(check.ok,JSON.stringify(check));record('generated pack passes script validator',check);
 const user=await request('/api/ui/scroll/state?pack='+pack);const bot=await tool('state',{pack});assert.deepEqual(user,bot);record('HTTP user and bot observe identical persisted state');
 const early=await request('/api/ui/scroll',{operation:'pack',pack},true);assert.equal(early.status,400);record('pending cards cannot ship');
 for(const chapter of user.active.review.chapters){await tool('review',{pack,chapter:chapter.id,action:'approve'});}
 const flags=(await tool('state',{pack})).active.review.chapters.flatMap(x=>x.cards).filter(x=>x.status==='flagged');
 if(process.argv.includes('--review')){
   const edits=JSON.parse(fs.readFileSync(process.argv[process.argv.indexOf('--review')+1]));
   for(const edit of edits){
     const row=flags.find(x=>x.card.id===edit.id);assert.ok(row,'Review must identify an actual flagged card');
     assert.equal(row.card.front,edit.front,'Review is bound to the inspected question');
     const card={...row.card,back:edit.back,explanation:edit.explanation,status:'approved'};delete card.flag;
     await tool('review',{pack,decisions:[{cardId:card.id,action:'edit',card}]});record('source-based individual correction',{before:row.card,after:card,reviewer:'Codex; development pilot, not Paul acceptance'});
   }
 }
 assert.equal((await tool('state',{pack})).active.review.chapters.flatMap(x=>x.cards).filter(x=>x.status==='flagged').length,0,'Disputed cards need a concrete individual review, see state');
 proof.archive=await tool('pack',{pack});record('reviewed source-bound archive written',proof.archive);
 proof.preview=await tool('preview',{pack});record('generated archive loaded into Mobile Studio phone project',proof.preview);
 const url=proof.preview.preview.url;
 const html=await fetch(base+url).then(r=>r.text());assert.ok(html.includes('load-pack.js'));const loaded=await fetch(base+url+'generated-pack.json').then(r=>r.json());assert.equal(loaded.meta.id,pack);assert.equal(loaded.cards.length,proof.archive.cards);record('phone preview serves actual generated cards');
 proof.stats=await tool('stats',{pack});record('actual card and study-hour costs derived',proof.stats);
 proof.send=await tool('send',{pack});const download=await fetch(proof.send.url);assert.equal(download.status,200);assert.equal((await download.arrayBuffer()).byteLength,proof.archive.bytes);const second=await fetch(proof.send.url);assert.equal(second.status,410);record('one-time download permits one archive only',{expires:proof.send.expires,qr:Boolean(proof.send.qrSvg),lan:proof.send.lanReachable});
 proof.finishedAt=new Date().toISOString();proof.ok=true;delete proof.error;save();
}
main().catch(error=>{proof.ok=false;proof.error=String(error.stack??error);save();console.error(proof.error);process.exitCode=1;});
