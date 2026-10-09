/* Pure block planner + actual FSRS card scheduling. No DOM or network calls.
 * Planning NEVER predicts exposure: only a completed teach interaction updates it. */
(function (root) {
  "use strict";
  var FS = root.FSRS;
  if (!FS && typeof require === "function") FS = require("./vendor/ts-fsrs.js");
  if (!FS) throw new Error("Load vendor/ts-fsrs.js before feed.js");
  var TEACH = {fact:1, explainer:1, worked:1, recap:1, formula:1, when:1, write:1, pattern:1, course_example:1, variations_traps:1};
  var RECALL = {flashcard:1, cloze:1, why:1, order:1, spot:1, your_exercise:1, pattern_drill:1, exercise_variant:1};
  var GRADED = Object.assign({truefalse:1, mcq:1}, RECALL), PRIOR = -1000;
  function isTeach(c) { return !!(c && TEACH[c.type] && !(c.type === "worked" && c.fade > 0)); }
  function isGraded(c) { return !!(c && (GRADED[c.type] || c.type === "worked" && c.fade > 0)); }
  function isRecall(c) { return !!(c && (RECALL[c.type] || c.type === "worked" && c.fade > 0)); }
  function conceptsOf(c) { var x = c && c.concepts || {}; return [].concat(x.teaches || [], x.tests || [], c && c.covers || []); }
  function needs(c) { var x = c.concepts || {}; return [].concat(x.requires || [], x.tests || []); }
  function shares(a,b) { return conceptsOf(a).some(function(x) {return conceptsOf(b).indexOf(x)>=0;}); }
  function clone(x) { return JSON.parse(JSON.stringify(x)); }
  function exposed(row,index,session) { return !!(row && row.exposedAt !== null && (row.exposureSession !== session || row.exposedAt < index)); }
  function practice(c,row) { return (c.phase === "practise" || (!c.phase && (c.type === "cloze" || c.type === "flashcard") && !row.practised)); }
  function hardEligible(ledger,c,index,session) {
    if (!needs(c).every(function(id) {return exposed(ledger[id],index,session);})) return false;
    if(c.requiresParts && !(c.concepts.tests || []).every(function(id){return c.requiresParts.every(function(part){return (ledger[id].parts || []).indexOf(part)>=0;});})) return false;
    return (c.concepts.tests || []).every(function(id) {
      var r=ledger[id]; if (r.exposureSession !== session || r.claimed && !c.part) return true;
      return index-r.exposedAt >= (practice(c,r) ? 2 : 8);
    });
  }
  function subject(c,pack) {
    var id=conceptsOf(c)[0], x=pack.concepts.find(function(r){return r.id===id;});
    return c.subject || x && x.subject || (pack.meta && pack.meta.subjects || ["default"])[0];
  }
  function buildBlock(ledger,schedule,pack,scope,now) {
    schedule=schedule || {}; scope=scope || {}; now=new Date(now || Date.now());
    var history=(schedule.history || []).slice(), used=Object.assign({},schedule.used || {}), out=[];
    var session=schedule.sessionId || "session", index=history.length, start=Math.floor(index/10)*10;
    var blockHistory=history.slice(start), subjectCard=blockHistory.find(function(c){return conceptsOf(c).length;}), blockSubject=scope.subject || (subjectCard && subject(subjectCard,pack));
    // A subject switch must not strand a miss whose five-card delay lands in
    // this block. Choose that subject at the boundary, before the miss is due.
    if(!blockSubject) {var pending=(schedule.misses || []).filter(function(m){return m.due+5>=index && m.due<=start+9;}).sort(function(a,b){return a.due-b.due;})[0];if(pending){var owner=pack.concepts.find(function(c){return c.id===pending.concept;});blockSubject=owner && owner.subject;}}
    var recent=(schedule.answers || []).slice(-10), accuracy=recent.length ? recent.filter(function(a){return a.result==="right";}).length/recent.length : .85;
    var newLimit=accuracy<.7 ? 2 : accuracy>.95 ? 5 : 4;
    var selected=new Set(scope.concepts || pack.concepts.map(function(c){return c.id;}));
    function includePrereqs(id) {var c=pack.concepts.find(function(c){return c.id===id;}); (c && c.prereqs || []).forEach(function(p){if(!selected.has(p)){selected.add(p);includePrereqs(p);}});}
    Array.from(selected).forEach(includePrereqs);
    var introduced=new Set(blockHistory.filter(function(c){return c._planning && c._planning.reason==="new";}).flatMap(function(c){return c.concepts.teaches || [];}));
    for (var slot=0;slot<10;slot++) {
      index=history.length; if(index>start+9 && out.length) break;
      var previous=history[index-1], candidates=[];
      var rolling=history.filter(isGraded), recall=rolling.filter(isRecall).length, tf=rolling.filter(function(c){return c.type==="truefalse";}).length;
      pack.cards.forEach(function(c) {
        if(out.some(function(chosen){return chosen.id===c.id;}))return;
        if(blockSubject && subject(c,pack)!==blockSubject) return;
        if(!conceptsOf(c).some(function(id){return selected.has(id);}) && c.type!=="recap") return;
        if(shares(c,previous)) return;
        if(isGraded(c)) {
          if(!hardEligible(ledger,c,index,session)) return;
          if(c.type==="worked") {var learner=ledger[(c.concepts.tests || [])[0]];if(!learner || learner.stability>7 || c.fade!==(learner.fade || 0))return;}
          if((schedule.misses || []).some(function(m){return index<m.due && (c.concepts.tests || []).indexOf(m.concept)>=0;})) return;
          var miss=(schedule.misses || []).find(function(m){return index>=m.due && index<=m.due+5 && (c.concepts.tests || []).indexOf(m.concept)>=0;});
          if(miss && c.id===miss.card && pack.cards.some(function(other){return other.id!==c.id && isGraded(other) && (other.concepts.tests || []).indexOf(miss.concept)>=0 && hardEligible(ledger,other,miss.due+5,session) && subject(other,pack)===subject(c,pack) && (isRecall(other) || recall*2>=rolling.length+1);})) return;
          var fs=(schedule.cards || {})[c.id], due=!!fs && new Date(fs.due)<=now;
          if(used[c.id] && !miss && !due) return;
          if((schedule.reviewCount || 0)+out.filter(isGraded).length>=60) return;
          if(!isRecall(c) && (recall*2<rolling.length+1 || (c.type==="truefalse" && (tf+1)*5>rolling.length+1))) return;
          var row=ledger[(c.concepts.tests || [])[0]], whyCount=history.slice(start).filter(function(x){return x.type==="why";}).length;
          if(c.type==="why" && whyCount>=1) return;
          var score=miss ? 1000+(c.id!==miss.card?20:0)+(index-miss.due)*3 : due ? 700+(now-new Date(fs.due))/864e5 : row.claimed && !row.right ? 650 : practice(c,row) ? 500 : 300;
          score+=isRecall(c)?20:0;
          if(accuracy<.7) score+=(c.type==="cloze" ? 30:0);
          if(previous) {var prevConcept=pack.concepts.find(function(x){return x.id===conceptsOf(previous)[0];});var cc=pack.concepts.find(function(x){return x.id===conceptsOf(c)[0];});if(prevConcept && cc && (prevConcept.chapter===cc.chapter || (prevConcept.confusableWith || []).indexOf(cc.id)>=0))score+=15;}
          candidates.push({card:c,score:score,reason:miss?"re-test":due?"review":practice(c,row)?"practise":"test"});
        } else if(isTeach(c) && !used[c.id]) {
          if(c.partIndex != null && !(c.concepts.teaches || []).every(function(id){var parts=ledger[id].parts || [];return pack.cards.filter(function(other){return other.partIndex<c.partIndex && isTeach(other) && (other.concepts.teaches || []).indexOf(id)>=0;}).every(function(other){return parts.indexOf(other.part)>=0;});})) return;
          if(!(c.concepts.requires || []).every(function(id){return (c.concepts.teaches || []).indexOf(id)>=0 && c.type!=="worked" || exposed(ledger[id],index,session);})) return;
          if(!(c.concepts.teaches || []).every(function(id){var cc=pack.concepts.find(function(x){return x.id===id;});return (cc && cc.prereqs || []).every(function(p){return exposed(ledger[p],index,session);});}))return;
          var isNew=(c.concepts.teaches || []).some(function(id){return ledger[id] && ledger[id].exposedAt===null;});
          if(isNew && introduced.size>=newLimit) return;
          if(c.type==="worked") {var r=ledger[(c.concepts.teaches || [])[0]];if(!r || r.exposedAt===null || r.stability>7 || (c.fade || 0)!==(r.fade || 0)) return;}
          if(!isNew && c.partIndex==null && c.type!=="worked" && c.type!=="recap" && !(c.concepts.teaches || []).some(function(id){return ledger[id].reteach;}))return;
          candidates.push({card:c,score:accuracy<.7 && c.type==="worked"?580:100,reason:isNew?"new":c.type});
        }
      });
      var asks=candidates.filter(function(x){return isGraded(x.card);}), teach=candidates.filter(function(x){return isTeach(x.card);});
      var run=0;for(var k=index-1;k>=0 && isTeach(history[k]);k--)run++;
      var done=(schedule.done || 0), limit=(schedule.goal || 20)+(schedule.extra || 0);
      if(done>=limit) {candidates=asks.filter(function(x){return x.reason==="review" || x.reason==="re-test";});asks=candidates;teach=[];}
      var retrieval=asks.length>0, askFirst=run>=2 || asks.some(function(x){return x.score>=500;}) || [2,4,5,7].indexOf(index%10)>=0;
      var pool=askFirst ? asks.length?asks:teach : teach.length?teach:asks;
      pool.sort(function(a,b){return b.score-a.score || a.card.id.localeCompare(b.card.id);});
      var pick=pool[0];
      if(!pick) {out.push({id:done>=limit?"goal":"end",type:done>=limit?"goal":"end",_planning:{reason:done>=limit?"goal":"no eligible cards",retrievalEligible:false,conditional:"No legal card fits exposure, lag, scope and mix constraints"}});break;}
      if(!blockSubject) blockSubject=subject(pick.card,pack);
      var card=clone(pick.card), exposure={};needs(card).forEach(function(id){exposure[id]=ledger[id] ? ledger[id].exposedAt:null;});
      var claimed={},exposureSessions={};needs(card).forEach(function(id){claimed[id]=!!ledger[id].claimed;exposureSessions[id]=ledger[id].exposureSession;});
      card._planning={reason:pick.reason,retrievalEligible:retrieval,exposure:exposure,claimed:claimed,exposureSessions:exposureSessions,sessionId:session,subject:blockSubject,accuracy:accuracy,newLimit:newLimit};
      if(pick.reason==="new") (card.concepts.teaches || []).forEach(function(id){introduced.add(id);});
      used[card.id]=(used[card.id] || 0)+1;out.push(card);history.push(card);
    }
    return out;
  }
  function create(pack,options) {
    options=options || {};var session=options.sessionId || new Date().toISOString()+":"+(options.seed || 7), ledger=clone(options.ledger || {});
    pack.concepts.forEach(function(c){if(!ledger[c.id])ledger[c.id]={state:c.prior?"reviewing":"unseen",exposedAt:c.prior?PRIOR:null,exposureSession:c.prior?"prior":session,practised:false,tested:0,right:0,claimed:false,recallSessions:[],fade:0};});
    return {pack:clone(pack),ledger:ledger,schedule:clone(options.schedule || {}),sessionId:session,feed:[],seen:-1,goal:options.goal || 20,done:0,extra:0,run:0,bestRun:0,misses:[],answers:[],used:{},rewards:0,seed:options.seed || 7,ended:false,log:[],scope:options.scope || {},reviewCount:0,retention:Math.max(.85,Math.min(.95,options.retention || .9)),now:options.now || null};
  }
  function release(s,from) {for(var i=from+1;i<s.feed.length;i++){var id=s.feed[i].id;if(s.used[id]){s.used[id]--;if(!s.used[id])delete s.used[id];}}}
  function plan(s,from,ahead) {
    s.feed.length=Math.min(s.feed.length,from+1);s.log.length=Math.min(s.log.length,from+1);
    if(s.ended)return s.feed;
    var cards=root.SSFeed.buildBlock(s.ledger,{history:s.feed,cards:s.schedule,used:s.used,sessionId:s.sessionId,answers:s.answers,misses:s.misses,done:s.done,goal:s.goal,extra:s.extra,reviewCount:s.reviewCount},s.pack,s.scope,s.now || Date.now()).slice(0,ahead || 10);
    cards.forEach(function(c){var i=s.feed.length,p=c._planning || {};s.feed.push(c);s.log.push({index:i,id:c.id,type:c.type,reason:p.reason,retrievalEligible:!!p.retrievalEligible,exposure:p.exposure || {},claimed:p.claimed || {},exposureSessions:p.exposureSessions || {},subject:p.subject,sessionId:s.sessionId,conditional:p.conditional});s.used[c.id]=(s.used[c.id] || 0)+1;});return s.feed;
  }
  function expose(s,c,index) {(c.covers || []).forEach(function(id){if(s.ledger[id])s.ledger[id].recapped=true;});(c.concepts.teaches || []).forEach(function(id){var r=s.ledger[id];if(c.part){r.parts=r.parts || [];if(r.parts.indexOf(c.part)<0)r.parts.push(c.part);}if(r.exposedAt===null){r.exposedAt=index;r.exposureSession=s.sessionId;r.state="exposed";}});}
  function knowThis(s,c,index) {expose(s,c,index);(c.concepts.teaches || []).forEach(function(id){s.ledger[id].claimed=true;});}
  function answer(s,c,index,result,ms) {
    if(c._result && c._result!=="skipped")return c._grade;
    c._result=result;if(s.log[index])s.log[index].result=result;if(result==="skipped")return null;
    var now=new Date(s.now || Date.now()), expected=(c.seconds || 15)*1000;
    var revealMs=c._revealMs != null ? c._revealMs : c._ui && c._ui.revealAt ? ms-(now.getTime()-c._ui.revealAt) : null;
    var instant=(c.type==="flashcard" || c.type==="cloze" || c.type==="why") && (revealMs===null || revealMs<1000);
    var grade=result==="wrong"?"again":ms>2*expected?"hard":ms<.5*expected && !instant?"easy":"good";
    var rating={again:FS.Rating.Again,hard:FS.Rating.Hard,good:FS.Rating.Good,easy:FS.Rating.Easy}[grade];
    var scheduler=FS.fsrs({request_retention:s.retention,enable_fuzz:false});
    var review=scheduler.next(s.schedule[c.id] || FS.createEmptyCard(now),now,rating);
    s.schedule[c.id]=review.card;c._grade=grade;s.reviewCount++;s.answers.push({card:c.id,index:index,result:result,grade:grade,at:now.toISOString(),session:s.sessionId,fsrs:review.log});
    (c.concepts.tests || []).forEach(function(id){var r=s.ledger[id];r.practised=r.practised || practice(c,r);r.tested++;r.stability=review.card.stability;
      r.fade=Math.max(0,Math.min(3,(r.fade || 0)+(result==="right"?1:-1)));
      if(result==="right") {r.right++;r.state=r.state==="mastered"?"mastered":r.claimed?"known":"reviewing";if(isRecall(c)){r.recallSessions=r.recallSessions || [];if(!r.recallSessions.some(function(x){return x.session===s.sessionId;}))r.recallSessions.push({session:s.sessionId,day:now.toISOString().slice(0,10)});if(r.recallSessions.length>=3 && new Set(r.recallSessions.map(function(x){return x.day;})).size>=2)r.state="mastered";}s.misses=s.misses.filter(function(m){return m.concept!==id;});}
      else {s.misses=s.misses.filter(function(m){return m.concept!==id;});s.misses.push({concept:id,card:c.id,due:index+5});if(r.claimed){r.claimed=false;r.state="exposed";r.reteach=true;}}
    });s.run=result==="right"?s.run+1:0;s.bestRun=Math.max(s.bestRun,s.run);return grade;
  }
  function checks(s) {
    var cards=s.feed.slice(0,s.seen+1), rows=s.log.slice(0,s.seen+1), failures={};
    function bad(id,value){(failures[id] || (failures[id]=[])).push(value);}
    cards.forEach(function(c,i){var row=rows[i] || {}, p=c._planning || {};
      if(isGraded(c)){needs(c).forEach(function(id){if(row.exposure[id]==null || (((row.exposureSessions || {})[id] || s.ledger[id].exposureSession)===row.sessionId && row.exposure[id]>=i))bad("G1",c.id);});
        (c.concepts.tests || []).forEach(function(id){var r=s.ledger[id];if(c.phase!=="practise" && !((c.type==="cloze" || c.type==="flashcard") && row.reason==="practise") && ((row.exposureSessions || {})[id] || r.exposureSession)===row.sessionId && !(row.claimed || {})[id] && i-row.exposure[id]<8)bad("G3",c.id);});
        if(c._result && c._result!=="skipped" && (!c._feedback || !c._feedback.verdict || c._feedback.answer==null || !c._feedback.reason || !c._feedback.source))bad("G5",c.id);
      }
      if(i>=2 && isTeach(c) && isTeach(cards[i-1]) && isTeach(cards[i-2]) && row.retrievalEligible)bad("G2",i);
      if(i && shares(c,cards[i-1]))bad("G7",i);
      if(i && Math.floor(i/10)===Math.floor((i-1)/10) && p.subject && cards[i-1]._planning && cards[i-1]._planning.subject && p.subject!==cards[i-1]._planning.subject)bad("G8",i);
      if(c.type==="reward" && isGraded(c))bad("G10",i);
      if(c._result==="wrong" && i+10<cards.length)(c.concepts.tests || []).forEach(function(id){var later=cards.slice(i+5,i+11).filter(function(x){return isGraded(x) && (x.concepts.tests || []).indexOf(id)>=0;});if(!later.length)bad("G6",c.id);else {var alternative=s.pack.cards.some(function(x){return x.id!==c.id && isGraded(x) && (x.concepts.tests || []).indexOf(id)>=0;});if(alternative && later[0].id===c.id)bad("G6",c.id+" repeated wording");}});
    });
    var graded=cards.filter(isGraded), recall=graded.filter(isRecall).length, tf=graded.filter(function(c){return c.type==="truefalse";}).length;
    if(recall*2<graded.length || tf*5>graded.length)bad("G4",recall+"/"+graded.length+" recall; "+tf+" truefalse");
    if(cards.filter(function(c){return c.type==="reward";}).length*20>cards.length)bad("G10","reward rate");
    Object.keys(s.ledger).forEach(function(id){var r=s.ledger[id], sessions=r.recallSessions || [];if(r.state==="mastered" && (new Set(sessions.map(function(x){return x.session;})).size<3 || new Set(sessions.map(function(x){return x.day;})).size<2))bad("G11",id);});
    var terminal=cards.findIndex(function(c){return c.type==="end" || c.type==="goal";});if(terminal>=0 && cards.slice(terminal+1).some(function(c){return isTeach(c)||isGraded(c);}) && !s.extra)bad("G9","cards after terminal");
    var text={G1:"Only exposed concepts are graded",G2:"Retrieval after at most two teachings when eligible",G3:"First test lag is at least eight cards",G4:"Recall at least half; truefalse at most one fifth",G5:"Verdict, correct answer, reason and source are shown",G6:"Miss returns five to ten cards later with different wording",G7:"Adjacent cards do not share concepts",G8:"Subject changes at block boundaries",G9:"Feed ends; continuation requires a deliberate action",G10:"Rewards at most one in twenty, never graded",G11:"Mastery needs three recall sessions over two days"};
    return Object.keys(text).map(function(id){return {id:id,text:text[id],ok:!failures[id],detail:(failures[id] || []).join(", ")};});
  }
  var api={buildBlock:buildBlock,create:create,plan:plan,fill:plan,release:release,expose:expose,see:expose,knowThis:knowThis,answer:answer,checks:checks,isTeach:isTeach,isGraded:isGraded,conceptsOf:conceptsOf,PRIOR:PRIOR,hardEligible:hardEligible};
  root.SSFeed=api;if(typeof module!=="undefined")module.exports=api;
})(typeof window!=="undefined"?window:globalThis);
