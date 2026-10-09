// Production HTTP backend and distributable plugin, using only the T5 loopback port.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import {spawn} from 'node:child_process';
const repo=process.cwd(),base='http://127.0.0.1:48151',python='C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe';
const checks=[],receipts=[];
const require=(condition,label)=>{assert.ok(condition,label);checks.push(label);};
const auth=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'content-type':'application/json'},body:'{}'});
require(auth.ok,'scratch backend accepts local session');
const cookie=auth.headers.getSetCookie().map(x=>x.split(';')[0]).join('; ');
async function request(url,body,allowFailed=false){
  const response=await fetch(base+url,{method:body?'POST':'GET',headers:{cookie,'content-type':'application/json'},body:body?JSON.stringify(body):undefined});
  const answer=await response.json();receipts.push({url,body,status:response.status,answer});
  if((!response.ok || !answer.ok) && !allowFailed)throw new Error(JSON.stringify(answer));
  let value=answer.data;
  while(value?.tool && value.result){if(value.ok===false && !allowFailed)throw new Error(value.error);value=value.result;}
  return value;
}
const call=(name,args,allowFailed=false)=>request('/api/ui/tools/call',{tool:'neyvia.'+name,arguments:args},allowFailed);
const catalog=await request('/api/ui/tools');
const required=['manual.project','manual.versions','manual.patch.apply','manual.demote','manual.recovery.bind','manual.recover','manual.compile','manual.compiled','manual.script.run'];
require(required.every(name=>catalog.tools.some(row=>row.name==='neyvia.'+name && row.available)),'all new commands registered in actual HTTP tool catalog');
const index=await request('/api/ui/manuals');require(index.manuals.some(row=>row.id==='manuals-next'),'actual app manual index includes grounded new workflow');
const child=spawn(python,[path.join(repo,'plugins/neyvia/mcp/neyvia_mcp.py')],{cwd:repo,env:{...process.env,NEYVIA_UI_BACKEND_URL:base},windowsHide:true,stdio:['pipe','pipe','pipe']});
const pending=new Map();let id=0;let stderr='';
child.stderr.on('data',chunk=>stderr+=chunk);
readline.createInterface({input:child.stdout}).on('line',line=>{const answer=JSON.parse(line);const p=pending.get(answer.id);if(p){clearTimeout(p.timer);pending.delete(answer.id);p.resolve(answer);}});
child.on('exit',code=>{for(const p of pending.values()){clearTimeout(p.timer);p.reject(new Error('Plugin exited '+code+': '+stderr));}});
async function rpc(method,params){
  const request={jsonrpc:'2.0',id:++id,method,params};
  const answer=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('Plugin timed out')),90000);pending.set(id,{resolve,reject,timer});child.stdin.write(JSON.stringify(request)+'\n');});
  receipts.push({interface:'plugin',request,answer});if(answer.error)throw new Error(answer.error.message);return answer.result;
}
async function plugin(name,args){const result=await rpc('tools/call',{name:'tools_call',arguments:{tool:'neyvia.'+name,arguments:args}});if(result.isError)throw new Error(result.content[0].text);return JSON.parse(result.content[0].text);}
try{
  await rpc('initialize',{protocolVersion:'2025-06-18',capabilities:{},clientInfo:{name:'T5-proof',version:'1'}});
  const tools=await rpc('tools/list',{});require(tools.tools.some(row=>row.name==='manual_project'),'distributable Claude plugin exposes state projection');
  for(const name of required){
    const described=await rpc('tools/call',{name:'tools_describe',arguments:{name:'neyvia.'+name}});
    require(!described.isError,'plugin discovers '+name);
  }
  const loaded=await plugin('manual.load',{id:'manuals-next',chapter:'scripts'});require(loaded.text.includes('manual.script.run'),'plugin loads actual grounded manual for script execution');
  const clock={id:'neyvia-reference',chapter:'time',procedure:'clock',inputs:{}};
  for(let i=0;i<3;i++){const run=await plugin('manual.run',clock);require(run.status==='completed' && run.checks.every(row=>row.passed),'plugin ordinary clock executes actual checks');}
  const compiled=await plugin('manual.compile',{...clock,minRuns:3});require(compiled.zeroToken,'actual HTTP log compiles deterministic clock');
  const result=await plugin('manual.script.run',{scriptId:compiled.scriptId,inputs:{}});
  require(result.status==='completed' && result.modelCalls===0 && result.checks.every(row=>row.passed),'plugin runs compiled script through actual HTTP backend with scope and checks');
  const observation=await plugin('manual.observe',{id:'manuals-next',chapter:'scripts',state:'current',reset:true});
  const projection=await plugin('manual.project',{handle:observation.handle,path:'/scripts',offset:0,limit:1});
  require(Array.isArray(projection.value) && projection.value.length===1,'plugin projects actual retained script state by durable handle');
  const denied=await rpc('tools/call',{name:'tools_call',arguments:{tool:'neyvia.manual.run',arguments:{id:'workspace',chapter:'files',procedure:'read-and-confirm',inputs:{path:'never-read.txt',phrase:'anything'}}}});
  require(denied.isError && denied.content[0].text.includes('PORTED'),'plugin cannot use manual execution to access excluded workspace tools');
  const failure=await call('manual.run',{id:'neyvia-reference',chapter:'time',procedure:'lap-and-stop',inputs:{id:'t5-missing-timer',lapId:'t5-lap',label:'missing fixture'}},true);
  require(failure.status==='failed','actual missing timer creates durable failure');
  const recipe=await plugin('manual.recovery.bind',{runId:failure.runId,chapter:'time',procedure:'clock',inputs:{}});
  const recovered=await plugin('manual.recover',{runId:failure.runId,recipeId:recipe.recipeId});
  require(recovered.status==='completed' && recovered.checks.every(row=>row.passed),'plugin recovery preserves narrowed scope through actual HTTP gateway');
  fs.writeFileSync(path.join(repo,'scripts/evidence/T5-http.json'),JSON.stringify({passed:true,at:new Date().toISOString(),base,checks,receipts},null,2)+'\n');
  console.log(JSON.stringify({passed:true,checks:checks.length,receipt:'scripts/evidence/T5-http.json'}));
}finally{child.stdin.end();await new Promise(resolve=>child.on('exit',resolve));}
