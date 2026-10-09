import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo=process.cwd(),root=mkdtempSync(path.join(tmpdir(),'neyvia-situation-http-'));
const child=spawn(resolveNeyviaPython(repo).python,['-u','-c',String.raw`
import json,sys
from pathlib import Path
from http.server import ThreadingHTTPServer
from grant_agent.web_backend import FluxioWebBackend,make_handler
r=Path(sys.argv[1]);b=FluxioWebBackend(r,r);b.sessions['fixture-token']={'username':'fixture','role':'admin'}
s=ThreadingHTTPServer(('127.0.0.1',0),make_handler(b));print(json.dumps({'port':s.server_address[1]}),flush=True);s.serve_forever()
`,root],{env:{...process.env,PYTHONPATH:path.join(repo,'src')},stdio:['ignore','pipe','pipe']});
let errors='';child.stderr.on('data',d=>{errors+=d;});
try {
 const ready=await new Promise((resolve,reject)=>{let buffer='';const timer=setTimeout(()=>reject(Error(errors || 'HTTP startup timeout')),30000);
  child.once('error',e=>{clearTimeout(timer);reject(e);});child.stdout.on('data',d=>{buffer+=d;if(buffer.includes('\n')){clearTimeout(timer);resolve(JSON.parse(buffer.split('\n')[0]));}});});
 async function invoke(verb,args={},authenticated=true){const response=await fetch(`http://127.0.0.1:${ready.port}/api/backend`,{method:'POST',headers:{'Content-Type':'application/json',...(authenticated?{Cookie:'grand_agent_session=fixture-token'}:{})},body:JSON.stringify({command:'call_situation_command',payload:{verb,workId:'http-proof',arguments:args,_operatorIdentity:'spoofed'}})});return {status:response.status,body:await response.json()};}
 assert.equal((await invoke('define',{task:'Inspect settings'},false)).status,401);
 const saved=await invoke('define',{task:'Inspect settings',constraints:['Do not publish'],acceptance:['Settings observed'],source:'invented-authority'});
 assert.equal(saved.body.ok,true,JSON.stringify(saved));assert.equal(saved.body.data.contract.source,'operator:fixture');assert.equal(saved.body.data.revision,1);
 assert.equal((await invoke('define',{task:'silently replace'})).body.ok,false);
 const recalled=await invoke('recall',{maxCharacters:2000});assert.equal(recalled.body.data.task.task,'Inspect settings');assert.equal(recalled.body.data.executionReady,false);
 assert.equal((await invoke('inspect',{facet:'contract'},false)).status,401);
 assert.equal((await invoke('inspect',{facet:'contract'})).body.data.contract.constraints[0],'Do not publish');
 assert.equal((await invoke('change',{})).body.ok,false);
 const invalid=await invoke('observe',{maxCharacters:10,url:'http://127.0.0.1:47908/control'});assert.equal(invalid.body.ok,false);assert.match(invalid.body.error,/budget/);
 const changed=await invoke('define',{task:'Inspect navigation',expectedRevision:1});assert.equal(changed.body.data.revision,2);
 console.log('SITUATION_HTTP_PASSED: login, operator identity, durable read/update, revision conflict, read-only Preview and invalid observation budget');
} finally {child.kill();await new Promise(resolve=>child.once('exit',resolve));rmSync(root,{recursive:true,force:true});}
