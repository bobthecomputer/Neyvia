import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {mkdirSync, writeFileSync} from 'node:fs';
import {resolve} from 'node:path';

const python = process.env.SCROLL_PYTHON || 'C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe';
function run(request) {
  const result = spawnSync(python, ['scripts/scroll_pack_probe.py'], {input: JSON.stringify(request), encoding: 'utf8', timeout: 45000});
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}
const text = 'The derivative is the slope of a tangent. The power rule states $\\frac{d}{dx}x^n = nx^{n-1}$.';
const sources = {'notes/chapter.md': text};
const concept = {id:'deriv', name:'Derivative', chapter:'derivatives', subject:'math', prereqs:[], kind:'formula', definition:'The derivative is tangent slope.'};
function card(type, number, extra={}) {
  return {id:`deriv.${type}.${String(number).padStart(2,'0')}`, type, chapter:'derivatives', subject:'math', body:'What does a derivative measure?', concepts:{teaches:type==='fact'?['deriv']:[],requires:[],tests:type==='fact'?[]:['deriv']}, source:{doc:'notes/chapter.md',span:[0,text.length]}, difficulty:.4, seconds:20, lang:'en', provenance:{stage:'fixture',tier:'script',runId:'validator-proof'}, ...extra};
}
const pack = {
  meta:{id:'validator-proof',title:'Derivatives',subjects:['math'],version:1,generator:'neyvia',created:new Date().toISOString(),lang:'en'},
  concepts:[concept],sources:[{id:'notes/chapter.md',title:'Notes',sha256:createHash('sha256').update(text).digest('hex'),kind:'markdown'}],generation:{run:'validator-proof',costs:[]},
  cards:[card('fact',1,{body:'Derivative: tangent slope. $\\frac{d}{dx}x^n=nx^{n-1}$.'}),card('flashcard',1,{front:'Derivative?',back:'Tangent slope',explanation:'It is the local rate of change.'}),card('cloze',1,{cloze:{before:'A derivative is tangent ',blank:'slope',after:'.'},explanation:'Slope describes local change.'}),card('mcq',1,{options:[{text:'Tangent slope',correct:true},{text:'Function height',correct:false,why:'Height is a value, not a rate.'}],explanation:'A derivative measures change.'})]
};
const checks = [];
function record(name, result) {checks.push({name,ok:true,...result});}
const valid = run({pack,sources});
assert.equal(valid.ok,true,JSON.stringify(valid.errors)); record('valid pack incl real KaTeX',valid);
const bad = [
  ['cycle','dag',p=>p.concepts[0].prereqs.push('deriv')],
  ['missing teaching reference','teach',p=>p.cards.splice(0,1)],
  ['graded teaches/tests overlap','graded-overlap',p=>p.cards[1].concepts.teaches.push('deriv')],
  ['invalid source span','source-span',p=>p.cards[1].source.span[1]+=1],
  ['malformed math','math',p=>p.cards[0].body='Bad $\\frac{1}{$'],
  ['two correct MCQ options','mcq',p=>p.cards[3].options[1].correct=true],
  ['bad chapter recall mix','mix',p=>p.cards=p.cards.filter(c=>c.type!=='flashcard'&&c.type!=='cloze')],
  ['wrong source hash','source-hash',p=>p.sources[0].sha256='0'.repeat(64)],
  ['fact length','length',p=>p.cards[0].body='word '.repeat(61)],
  ['invalid type schema','schema',p=>p.cards[0].type='reward'],
];
for (const [name,rule,mutate] of bad) {
  const broken=structuredClone(pack);mutate(broken);
  const result=run({pack:broken,sources});
  assert.equal(result.ok,false,name);assert(result.errors.some(e=>e.rule===rule),JSON.stringify(result));
  record(name,{errors:result.errors});
}
const roundtrip=run({operation:'roundtrip',pack,sources});assert(roundtrip.ok);record('persisted source archive roundtrip',roundtrip);
const bom=structuredClone(pack);bom.sources[0].textSha256=bom.sources[0].sha256;bom.sources[0].sha256=createHash('sha256').update(Buffer.concat([Buffer.from([239,187,191]),Buffer.from(text)])).digest('hex');
assert(run({pack:bom,sources}).ok);assert(run({operation:'roundtrip',pack:bom,sources}).ok);record('BOM source byte hash and decoded text hash',{});
for (const name of ['../escape.txt','C:/escape.txt','media/../escape.txt','media\\escape.txt']) {
  const attack=run({operation:'archive-attack',entries:[[name,'malicious']]});assert.equal(attack.ok,false);assert.match(attack.error,/unsafe archive path/);record(`archive rejects ${name}`,attack);
}
const duplicate=run({operation:'archive-attack',entries:[['pack.json','{}'],['pack.json','{}']]});assert.equal(duplicate.ok,false);record('archive rejects duplicate members',duplicate);
const rows=[{stage:'wording',tier:'small',model:'sample-model',inTokens:100,outTokens:50,cachedTokens:25,ms:4,ok:true}];
const stats=run({operation:'stats',rows,cards:pack.cards,prices:{'sample-model':{input:2,output:8,cached:.5}},review:[{cardId:pack.cards[0].id,action:'approve'},{cardId:pack.cards[1].id,action:'edit'},{cardId:pack.cards[1].id,action:'approve'}]});
assert.equal(stats.totalUsd,.0005625);assert.equal(stats.approveWithoutEditRate,.5);assert.equal(stats.costPerStudyHour.reviewCost,0);assert.equal(stats.costPerStudyHour.usd,.0005625*45);record('cached input and study-hour cost arithmetic',{stats});
const unknown=run({operation:'stats',rows,cards:pack.cards});assert.equal(unknown.totalUsd,null);record('unknown list price remains null',{});
const unknownUsage=run({operation:'stats',rows:[{stage:'wording',tier:'small',model:'sample-model'}],cards:pack.cards,prices:{'sample-model':{input:2,output:8,cached:.5}}});assert.equal(unknownUsage.totalUsd,null);record('missing provider usage remains null',{});
const unavailableUsage=run({operation:'stats',rows:[{...rows[0],usageKnown:false}],cards:pack.cards,prices:{'sample-model':{input:2,output:8,cached:.5}}});assert.equal(unavailableUsage.totalUsd,null);record('usageKnown false remains null',{});
const reviewMap=run({operation:'stats',rows,cards:pack.cards,review:{a:{status:'approved'},b:{status:'approved',edited:true}}});assert.equal(reviewMap.approveWithoutEditRate,.5);record('service review map preserves edits',{});
const receipt={ok:true,created:new Date().toISOString(),checks};
mkdirSync('.agent_control/scroll-study',{recursive:true});
writeFileSync('.agent_control/scroll-study/validator-proof.json',JSON.stringify(receipt,null,2));
console.log(JSON.stringify({ok:true,checks:checks.length,brokenPacksRejected:bad.length,receipt:resolve('.agent_control/scroll-study/validator-proof.json')}));
