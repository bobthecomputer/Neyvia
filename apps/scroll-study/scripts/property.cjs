/* Random DAG/history checks exercise the real planner + actual vendored FSRS.
 * G5 here checks feedback receipts. Its rendered presence is a separate browser gate.
 * No test invents exposure; failed/flicked teaching stays unseen. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const F = require('../www/feed.js');
const Storage = require('../www/storage.js');
let seed = 7319;
function rand() {seed = (Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;}
function makePack(n,multipleSubjects=false) {
  const concepts=[],cards=[];
  for(let i=0;i<n;i++) {
    const id='c'+i, prereqs=i && rand()<.45 ? ['c'+Math.floor(rand()*i)] : [];
    concepts.push({id,name:id,subject:multipleSubjects && i%2 ? 'mathematics':'science',chapter:'foundations',prereqs,kind:'fact'});
    for(const [type,phase,suffix] of [['fact','teach','t'],['cloze','practise','p'],['flashcard','test','a'],['why','test','b'],['order','test','c']]) {
      cards.push({id:id+'.'+suffix,type,phase,seconds:8,concepts:{teaches:phase==='teach'?[id]:[],tests:phase==='teach'?[]:[id],requires:phase==='teach'?prereqs:[id]},source:{doc:'notes.md',span:[0,10]},explanation:'From the study notes.',answer:'answer',items:['a','b']});
    }
  }
  return {meta:{id:'property',subjects:['science']},concepts,cards,sources:[{id:'notes.md'}]};
}
const totals=Object.fromEntries(Array.from({length:11},(_,i)=>['G'+(i+1),0]));
let answers=0, sessions=0, snapshots=0;
for(let trial=0;trial<150;trial++) {
  if(trial%25===0)console.error('property trial',trial);
  const pack=makePack(12+Math.floor(rand()*15),trial%3===0);let ledger,schedule;
  for(let day=0;day<3;day++) {
    const now=new Date(Date.UTC(2026,9,4+day)), s=F.create(pack,{ledger,schedule,goal:35,sessionId:trial+':'+day,now:now.toISOString()});
    for(let i=0;i<75;i++) {
      const before=JSON.stringify({ledger:s.ledger,schedule:s.schedule,feed:s.feed});
      const pureSchedule={history:s.feed,cards:s.schedule,sessionId:s.sessionId,used:s.used,misses:s.misses,answers:s.answers,done:s.done,goal:s.goal};
      const a=F.buildBlock(s.ledger,pureSchedule,pack,{},now);
      a.forEach((c,offset)=>{if(F.isGraded(c))assert.ok(F.hardEligible(s.ledger,c,s.feed.length+offset,s.sessionId),'every emitted question obeys exposure and lag');const prev=offset?a[offset-1]:s.feed[s.feed.length-1];if(prev)assert.ok(!F.conceptsOf(c).some(id=>F.conceptsOf(prev).includes(id)),'every emitted card obeys adjacency');});
      assert.equal(JSON.stringify(a),JSON.stringify(F.buildBlock(s.ledger,pureSchedule,pack,{},now)),'deterministic block');
      assert.equal(before,JSON.stringify({ledger:s.ledger,schedule:s.schedule,feed:s.feed}),'pure block does not mutate');snapshots++;
      F.release(s,i-1);F.plan(s,i-1,3);const c=s.feed[i];if(!c)break;s.seen=i;
      if(c.type==='goal' || c.type==='end')break;
      if(F.isTeach(c)){if(rand()>.18){if(rand()<.05)F.knowThis(s,c,i);else F.expose(s,c,i);s.done++;}}
      else if(F.isGraded(c)) {
        if(rand()<.09){F.answer(s,c,i,'skipped',0);continue;}
        c._feedback={verdict:'correct or incorrect',answer:'answer',reason:c.explanation,source:c.source};
        c._revealMs=rand()<.4?200:2500;
        const grade=F.answer(s,c,i,rand()<.83?'right':'wrong',1000+rand()*18000);
        if(c._revealMs<1000 && ['flashcard','cloze','why'].includes(c.type))assert.notEqual(grade,'easy');
        assert.equal(s.schedule[c.id].reps,s.answers.filter(x=>x.card===c.id).length+(schedule && schedule[c.id]?schedule[c.id].reps:0));
        assert.ok(s.schedule[c.id].stability>0);answers++;s.done++;
      }
    }
    const checks=F.checks(s);
    for(const check of checks) {totals[check.id]++;assert.ok(check.ok,`trial ${trial}, day ${day}, ${check.id}: ${check.detail}`);}
    const progress=JSON.parse(Storage.exportProgress(s));assert.equal(Storage.validate(progress,pack),progress);
    ledger=s.ledger;schedule=s.schedule;sessions++;
  }
}
// Constructive three-session/two-day mastery proof; instant reveal cannot be Easy.
const masteryPack=makePack(3);let ledger,schedule;
for(let session=0;session<3;session++) {
  const s=F.create(masteryPack,{ledger,schedule,sessionId:'mastery'+session,now:new Date(Date.UTC(2026,9,4+(session===2?1:0))).toISOString()});
  if(!ledger)F.expose(s,masteryPack.cards[0],0);
  const c=structuredClone(masteryPack.cards[2]);c._revealMs=100;F.answer(s,c,10,'right',100);
  assert.notEqual(c._grade,'easy');assert.equal(s.ledger.c0.state,session===2?'mastered':'reviewing');ledger=s.ledger;schedule=s.schedule;
}
// Deliberate corruption must be caught, not blessed by the planner's own assertions.
const workedPack=makePack(2);workedPack.concepts.forEach(c=>{c.prior=true;c.prereqs=[];});
workedPack.cards=[0,1,2].map(fade=>({id:'c0.worked.01'+(fade?'.f'+fade:''),type:'worked',fade,seconds:30,steps:[{text:'First step'},{text:'Second step'}],concepts:{teaches:fade?[]:['c0'],tests:fade?['c0']:[],requires:[]}}));
for(const fade of [0,1,2]){
 const ws=F.create(workedPack);ws.ledger.c0.fade=fade;ws.ledger.c0.stability=2;
 const block=F.buildBlock(ws.ledger,{},workedPack,{},new Date());
 assert.equal(block[0].fade,fade,'only the current scaffold is emitted');assert.equal(F.isGraded(block[0]),fade>0);
 ws.ledger.c0.stability=8;assert.equal(F.buildBlock(ws.ledger,{},workedPack,{},new Date())[0].type,'end','stable concepts do not get worked scaffolds');
}
const p=makePack(2), broken=F.create(p), question=structuredClone(p.cards[2]);
broken.feed=[question];broken.log=[{index:0,sessionId:broken.sessionId,exposure:{c0:null}}];broken.seen=0;
assert.equal(F.checks(broken).find(c=>c.id==='G1').ok,false);
// Honest infeasibility: a one-concept new pack cannot interleave or reach lag2.
// It ends with an explicit conditional reason, rather than asking an unseen idea.
const sparse=makePack(1), ss=F.create(sparse);F.plan(ss,-1,10);assert.equal(ss.feed[0].type,'fact');
ss.seen=0;F.expose(ss,ss.feed[0],0);F.release(ss,0);F.plan(ss,0,10);assert.equal(ss.feed[1].type,'end');assert.ok(ss.feed[1]._planning.conditional);
const report={ok:true,seed:7319,trials:150,sessions,snapshots,answers,checks:totals,fsrs:'ts-fsrs 5.4.2',mutationCaught:'G1',conditional:[{case:'one-concept pack',constraints:['G3 lag','G7 adjacency'],result:'ends without unsafe retrieval; full rhythm is impossible'}],boundary:'G5 receipts are fixture evidence; real rendered feedback and IndexedDB require browser journey'};
const output=path.join(__dirname,'property-results.json');fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
