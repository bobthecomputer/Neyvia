import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
const repo=path.resolve(import.meta.dirname,'..'),base='http://127.0.0.1:48591',root=path.join(repo,'.agent_control/a3b/runtime');
const login=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'content-type':'application/json'},body:'{}'});
const cookie=login.headers.getSetCookie().map(x=>x.split(';')[0]).join(';'),checks=[];
async function call(operation,args={},denied=false){const r=await fetch(base+'/api/ui/scroll',{method:'POST',headers:{'content-type':'application/json',cookie},body:JSON.stringify({operation,...args})});const d=await r.json();if(denied){assert.equal(r.status,400);return d;}assert.ok(r.ok,JSON.stringify(d));return d.data??d;}
function record(name,data){checks.push({name,data});console.log(name);}
const jobBefore=await call('job',{requestId:'a3b-learning-final-warm'});
const log=path.join(root,'.neyvia/scroll/learning-notes/generation.jsonl'),bytes=fs.readFileSync(log);
const replay=await call('generate',{pack:'learning-notes',requestId:'a3b-learning-final-warm'});assert.ok(replay.replayed);assert.equal(replay.job.pid,jobBefore.job.pid);assert.deepEqual(fs.readFileSync(log),bytes);record('backend restart retains completed job identity without provider reexecution',replay);
for(const paths of [[],[path.resolve(root,'../../outside.md')],[path.join(root,'password.txt')]])record('invalid or out-of-scope source refused',await call('import',{paths,packId:'boundary-pack'},true));
const a=path.join(root,'boundary-a.md'),b=path.join(root,'boundary-b.md');fs.writeFileSync(a,'# Atomic state\nA revision identifies a persisted state.\n');fs.writeFileSync(b,'# Durable requests\nA request identity prevents duplicate execution.\n');
await call('import',{paths:[a],packId:'boundary-pack'});const repeated=await call('import',{paths:[a],packId:'boundary-pack'});assert.ok(repeated.replayed);
const extended=await call('import',{paths:[b],packId:'boundary-pack'});assert.equal(extended.pack.sources.length,2);assert.ok(fs.readdirSync(path.join(root,'.neyvia/scroll/boundary-pack/history')).length);record('import retry deduplicates; extension retains source history',extended.pack.sources);
const before=await call('state',{pack:'learning-notes'}),row=before.active.review.chapters[0].cards.find(x=>x.type==='truefalse');
const invalid={...row.card,source:{doc:'missing',span:[0,2]}};record('invalid edit refuses atomically',await call('review',{pack:'learning-notes',decisions:[{cardId:row.id,action:'edit',card:invalid}]},true));
assert.deepEqual((await call('state',{pack:'learning-notes'})).active,before.active);
await call('review',{pack:'learning-notes',decisions:[{cardId:row.id,action:'drop'}]});await call('review',{pack:'learning-notes',chapter:row.card.chapter,action:'approve'});
assert.equal((await call('state',{pack:'learning-notes'})).active.review.chapters.flatMap(x=>x.cards).find(x=>x.id===row.id).status,'dropped');
await call('review',{pack:'learning-notes',decisions:[{cardId:row.id,action:'approve'}]});record('chapter approval preserves a deliberate drop',true);
const send=await call('send',{pack:'learning-notes'});assert.ok(send.qrSvg?.includes('<svg'));const first=await fetch(send.url);assert.equal(first.status,200);const archive=await first.arrayBuffer();assert.equal((await fetch(send.url)).status,410);record('HTTP SVG QR delivers one download then refuses reuse',{expires:send.expires,svgBytes:send.qrSvg.length,archiveBytes:archive.byteLength,lanReachable:send.lanReachable});
fs.writeFileSync(path.join(repo,'scripts/evidence/A3B-boundaries.json'),JSON.stringify({ok:true,at:new Date().toISOString(),checks},null,2));
