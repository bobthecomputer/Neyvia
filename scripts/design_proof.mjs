// Verify owned Obscura artifacts, never substitute source checks for rendered states.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
const root=path.resolve(import.meta.dirname,'..'), base=path.resolve('D:/NeyviaRuns/gui');
const mode=process.argv[2];
if(!['screens','states'].includes(mode)) throw new Error('Choose screens or states');
const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const failures=[],screens=[],journeys=[];
const assert=(ok,message)=>{if(!ok)failures.push(message);};
const admitted=new Set(['C2g-engine-fragment-admission.json','C2h-engine-admission.json'].map(p=>read(path.join(root,'scripts/evidence',p)).engineBinary.sha256));
function verify(receipt,label){
  assert(admitted.has(receipt.engine?.sha256),`${label}: unadmitted engine`);
  for(const screen of receipt.screens||[]){
    const file=path.resolve(screen.path||'');
    const owned=file.toLowerCase().startsWith((base+path.sep).toLowerCase());
    assert(owned,`${label}: screenshot outside owned evidence`);
    if(owned)assert(fs.existsSync(file)&&hash(file)===screen.sha256,`${label}: screenshot changed ${screen.path}`);
    screens.push({...screen,set:receipt.set});
  }
}
let result;
if(mode==='screens'){
  for(const set of ['before','after'])for(const theme of ['dark','light']){
    const p=path.join(base,set,`receipt-${theme}.json`);
    if(!fs.existsSync(p)){failures.push(`Missing ${p}`);continue;}
    const r=read(p);verify(r,`${set}/${theme}`);
    assert(r.errors?.length===0,`${set}/${theme}: capture error`);
    assert(r.buildIndexSha256===hash(path.join(base,`build-${set}`,'index.html')),`${set}/${theme}: stale build`);
    for(const name of ['Shell','Settings','App Factory','Files','Notes'])assert(r.screens.some(s=>s.screen===name&&s.theme===theme),`${set}/${theme}: missing ${name}`);
    if(set==='after'){
      const journey=r.journeys?.find(j=>j.theme===theme&&j.name==='Text size');
      assert(!!journey,`${set}/${theme}: missing Look text-size journey`);
      if(journey){
        const file=path.resolve(journey.path||'');
        const owned=file.toLowerCase().startsWith((base+path.sep).toLowerCase());
        assert(owned&&fs.existsSync(file)&&hash(file)===journey.sha256,`${set}/${theme}: changed Look screenshot`);
        assert(Number.isFinite(journey.medium)&&journey.medium>0&&Number.isFinite(journey.large)&&Math.abs(journey.large/journey.medium-1.1)<.015,`${set}/${theme}: text scale differs from 1.1`);
        assert(r.checks?.some(c=>c.theme===theme&&c.name==='Look large text scales once'&&c.passed===true),`${set}/${theme}: text-size control failed`);
        journeys.push(journey);
      }
    }
  }
  result={schema:'neyvia.gui-rendered-screens.v1',complete:failures.length===0,screens,journeys,failures};
  fs.writeFileSync(path.join(root,'scripts/evidence/GUI-rendered-screens.json'),JSON.stringify(result,null,2)+'\n');
  if(!failures.length){
    const pairs=['Shell','Settings','App Factory','Files','Notes'].flatMap(name=>['dark','light'].map(theme=>({name,theme,before:screens.find(s=>s.screen===name&&s.theme===theme&&s.set==='before'),after:screens.find(s=>s.screen===name&&s.theme===theme&&s.set==='after')})));
    const relative=p=>path.relative(base,p).replaceAll('\\','/');
    fs.writeFileSync(path.join(base,'index.html'),`<!doctype html><meta charset="utf-8"><title>Neyvia style proof</title><style>body{font:15px system-ui;background:#101714;color:#edf2ea;margin:24px}h1{font-weight:500}section{margin:32px 0}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}img{width:100%;height:auto}figure{margin:0}figcaption{margin:8px 0;color:#b5c6bc}@media(max-width:700px){.pair{grid-template-columns:1fr}}</style><h1>Neyvia style comparison</h1><p>Actual owned Obscura screenshots. Left: baseline. Right: token cleanup. Source and contrast gates do not imply all interaction states passed; see the separate state receipt.</p>${pairs.map(p=>`<section><h2>${p.name} · ${p.theme}</h2><div class="pair"><figure><img src="${relative(p.before.path)}" alt="${p.name} before ${p.theme}"><figcaption>Before</figcaption></figure><figure><img src="${relative(p.after.path)}" alt="${p.name} after ${p.theme}"><figcaption>After</figcaption></figure></div></section>`).join('')}`);
  }
}else{
  const p=path.join(base,'after/receipt-lab-latest.json');
  const r=read(p);verify(r,'shared controls');
  const names=['hover fill changes','press feedback','keyboard input focus-visible','focus ring visible','loading is native disabled and named','disabled click no-op','radio arrows skip disabled option','reduced motion disables CSS duration','phone has no horizontal overflow'];
  for(const theme of ['dark','light'])for(const name of names)assert(r.checks?.some(c=>c.theme===theme&&c.name===name&&c.passed===true),`${theme}: ${name}`);
  assert(r.buildIndexSha256===hash(path.join(base,'build-lab-after/design-lab.html')),'shared controls: stale build');
  result={schema:'neyvia.gui-rendered-states.v1',complete:failures.length===0,checks:r.checks,observations:r.observations,receipt:p,screens,failures};
  fs.writeFileSync(path.join(root,'scripts/evidence/GUI-rendered-states.json'),JSON.stringify(result,null,2)+'\n');
}
console.log(JSON.stringify({mode,complete:result.complete,screens:screens.length,failures}));
if(failures.length)process.exitCode=1;
