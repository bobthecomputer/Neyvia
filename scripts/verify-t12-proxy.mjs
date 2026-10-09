// Real Vite proxy/session/resource calls; this does not claim rendered UI proof.
import fs from 'node:fs';
import path from 'node:path';
const receipt=JSON.parse(fs.readFileSync('scripts/evidence/T12.json','utf8'));
const base='http://127.0.0.1:48262', checks=[];let cookie;
async function call(url,body,extra={}){const res=await fetch(base+url,{method:body?'POST':'GET',headers:{...(body?{'Content-Type':'application/json'}:{}),...(cookie?{Cookie:cookie}:{}),Origin:base,...extra},...(body?{body:JSON.stringify(body)}:{})});const set=res.headers.get('set-cookie');if(set)cookie=set.split(';')[0];return res;}
function check(name,passed,observed){checks.push({name,passed,observed});if(!passed)throw Error(name+' failed');}
await call('/api/auth/local-session',{});
try{
 const res=await call('/api/backend',{command:'gamedev_status_command',payload:{}});const status=await res.json();check('proxy calls owner commands',status.ok,status.data?.browserUrl);
 const project=receipt.project, query='?project='+encodeURIComponent(project);
 const html=await call('/api/gamedev/browser'+query);const markup=await html.text();check('same-origin browser runtime served through Vite',html.ok&&markup.includes('new NeyviaScene')&&html.headers.get('x-frame-options')==='SAMEORIGIN',{status:html.status,frame:html.headers.get('x-frame-options')});
 const runtime=await call('/api/gamedev/static/scene-runtime.js');check('same-origin native runtime resource served',runtime.ok&&(await runtime.text()).includes('class NeyviaScene'),runtime.status);
 const persisted=await (await call('/api/gamedev/browser-state'+query)).json();check('proxy reads persisted native scene',persisted.ok&&persisted.data.scene.meshes.length>0,{meshes:persisted.data?.scene?.meshes?.length});
 const config=JSON.parse(fs.readFileSync(path.join(project,'.neyvia/gamedev-bridge.json'),'utf8'));
 const registered=await (await call('/api/gamedev/bridge/register',{engine:'babylon',projectPath:project,context:'Edit',environment:'proxy-transport-only',capabilities:[]},{Authorization:'Bearer '+config.token})).json();
 check('same-origin proxy bridge registration accepted',registered.ok,{sessionId:registered.data?.sessionId,transportOnly:true});
 const rejected=await call('/api/gamedev/bridge/poll',{sessionId:registered.data?.sessionId},{Authorization:'Bearer '+config.token,Origin:'https://untrusted.invalid'});check('foreign-origin capability request refused',rejected.status===403,rejected.status);
 receipt.devProxy={base,boundary:'Authenticated transport/resources only; no rendered pixels or input claim',checks};
 fs.writeFileSync('scripts/evidence/T12.json',JSON.stringify(receipt,null,2)+'\n');console.log(JSON.stringify({passed:checks.every(c=>c.passed),checks:checks.length}));
}finally{await call('/api/auth/logout',{});}
