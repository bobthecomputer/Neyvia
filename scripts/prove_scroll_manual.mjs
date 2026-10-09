import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
const repo=path.resolve(import.meta.dirname,'..'),base='http://127.0.0.1:48591',root=path.join(repo,'.agent_control/a3b/runtime');
const login=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'content-type':'application/json'},body:'{}'});assert.ok(login.ok);
const cookie=login.headers.getSetCookie().map(x=>x.split(';')[0]).join(';');
async function tool(name,args){const r=await fetch(base+'/api/ui/tools/call',{method:'POST',headers:{'content-type':'application/json',cookie},body:JSON.stringify({tool:'neyvia.'+name,arguments:args})});const d=await r.json();assert.ok(r.ok&&d.ok!==false,JSON.stringify(d));const receipt=d.data??d;assert.notEqual(receipt.ok,false,JSON.stringify(receipt));return receipt.result??receipt;}
const proof={at:new Date().toISOString(),checks:[]};
proof.grounded=await tool('manual.validate',{id:'scroll-generator'});
for(let i=0;i<3;i++){const r=await tool('manual.run',{id:'scroll-generator',chapter:'overview',procedure:'validate-pack',inputs:{pack:'learning-notes'}});assert.equal(r.status,'completed',JSON.stringify(r));proof.checks.push(r);}
proof.compiled=await tool('manual.compile',{id:'scroll-generator',chapter:'overview',procedure:'validate-pack',inputs:{pack:'learning-notes'},minRuns:3});assert.ok(proof.compiled.zeroToken);
proof.replay=await tool('manual.script.run',{scriptId:proof.compiled.scriptId,inputs:{pack:'learning-notes'}});assert.equal(proof.replay.status,'completed');
fs.mkdirSync(path.join(root,'.neyvia/scroll'),{recursive:true});
fs.writeFileSync(path.join(root,'.neyvia/scroll/validation-script.json'),JSON.stringify({pack:'learning-notes',scriptId:proof.compiled.scriptId}));
fs.writeFileSync(path.join(repo,'scripts/evidence/A3B-manual.json'),JSON.stringify(proof,null,2));
console.log(JSON.stringify({ok:true,sourceRuns:proof.compiled.sourceRuns.length,zeroToken:true,compiled:proof.compiled.scriptId}));
