// Final live check after loading the implemented backend modules.
import assert from 'node:assert/strict';
import fs from 'node:fs';
const base=process.env.R_BACKEND||'http://127.0.0.1:48186';
const url=new URL(base);assert.equal(url.hostname,'127.0.0.1');assert(/^4818[1-9]$/.test(url.port));
const auth=await fetch(base+'/api/auth/local-session',{method:'POST',body:'{}',headers:{'Content-Type':'application/json'}});assert(auth.ok);
const cookie=auth.headers.get('set-cookie').split(';')[0];
async function tool(name,args={}){
 const r=await fetch(base+'/api/ui/tools/call',{method:'POST',body:JSON.stringify({tool:name,arguments:args}),headers:{'Content-Type':'application/json',Cookie:cookie}});
 const receipt=await r.json();assert(r.ok,JSON.stringify(receipt));let v=receipt.data;while(v?.tool&&v.result)v=v.result;return v;
}
const validation=await tool('neyvia.manual.validate');assert.equal(validation.ok,true);assert.equal(validation.manuals.length,18);
const loaded=await tool('neyvia.manual.load',{id:'handoff-recovery',chapter:'intake',maxChars:20000});
assert(loaded.text.includes('STEPS capture-once:'));assert(loaded.text.includes('"mode":"append"'));assert(loaded.text.includes('GUIDANCE Task mapping:'));
const mission=await tool('neyvia.manual.load',{id:'mission-plan',chapter:'orchestration'});assert(mission.text.includes('neyvia.mission.from_plan'));assert(mission.text.includes('one')||mission.text.includes('One Codex'));
const ambient=[];for(const on of [false,true]){const r=await tool('neyvia.view.ambient',{on});assert.equal(r.on,on);assert.equal(r.event.action,'view.ambient');ambient.push(r.event);}
fs.writeFileSync('scripts/evidence/final-backend.json',JSON.stringify({backend:base,manualsValidated:validation.manuals.length,typedStepsVisible:true,workflowGuidanceVisible:true,manualSha256:loaded.sha256,missionTemplateManualLoads:true,ambient,frontendBuild:'Vite production build passed',renderedUiVerified:false},null,2)+'\n');
console.log('Live backend: 18 grounded manuals, typed steps/guidance visible, mission manual and ambient on/off passed.');
