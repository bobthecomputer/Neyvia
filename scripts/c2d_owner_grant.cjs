/* Explicit owner regrant after native navigation; never triggered by page content. */
const fs=require('node:fs');
const http=require('node:http');
const [port,id]=process.argv.slice(2);if(port!=='48721'||!id)throw Error('Explicit C2d backend48721 and frozen task ID required');
const run=JSON.parse(fs.readFileSync('scripts/evidence/C2d-webvoyager-final.json'));
const task=run.tasks.find(t=>t.id===id);if(!task?.tabId||task.status!=='running')throw Error('Only the operator-selected running frozen task may be regranted');
let cookie;
function request(route,body){return new Promise((resolve,reject)=>{const data=JSON.stringify(body),q=http.request({host:'127.0.0.1',port,path:route,method:'POST',headers:{'Content-Type':'application/json','Content-Length':Buffer.byteLength(data),Connection:'close',...(cookie?{Cookie:cookie}:{})}},r=>{let raw='';r.setEncoding('utf8');r.on('data',s=>{raw+=s;if(raw.length>2000000)q.destroy(Error('Owner response limit'));});r.on('end',()=>{try{resolve({ok:r.statusCode>=200&&r.statusCode<300,headers:r.headers,value:JSON.parse(raw)});}catch(e){reject(e);}});});q.setTimeout(40000,()=>q.destroy(Error('Owner request timed out; no automatic replay')));q.on('error',reject);q.end(data);});}
async function api(op,args={}){const r=await request('/api/ui/browser',{op,args}),value=r.value;if(!r.ok||value.ok===false)throw Error(JSON.stringify(value));return value;}
async function main(){const login=await request('/api/auth/local-session',{});if(!login.ok)throw Error('Local owner session unavailable');cookie=login.headers['set-cookie'][0].split(';')[0];
 const visible=process.argv.includes('--visible');
 if(visible){const layout=await api('layout',{tabs:[{tabId:task.tabId,x:0,y:0,width:1200,height:730,visible:true}]});if(layout.actionId)await api('wait',{actionId:layout.actionId,timeoutMs:30000});}
 let obs=await api('observe',{tabId:task.tabId,cached:!visible});if(obs.actionId){const r=await api('wait',{actionId:obs.actionId,timeoutMs:30000});obs=r.result?.observation||r.result||r;}
 if(obs.authentication?.required)throw Error('Owner login required; no automated regrant');
 const state=await api('state');const tab=state.tabs.find(t=>t.id===task.tabId);if(!tab||tab.loading)throw Error('Wait for native navigation completion before explicit regrant');
 const grant=await api('tab.grant',{tabId:task.tabId,enabled:true});if(grant.actionId)await api('wait',{actionId:grant.actionId,timeoutMs:30000});
 const receipt={at:new Date().toISOString(),taskId:id,tabId:task.tabId,url:obs.url,revision:obs.revision,grantEpoch:grant.tab?.grantEpoch,visible,source:'explicit owner operator after observed navigation',secretsStored:false};fs.appendFileSync('scripts/evidence/C2d-owner-grants.jsonl',JSON.stringify(receipt)+'\n');console.log(JSON.stringify(receipt));
}
main().catch(e=>{console.error(e.message);process.exitCode=1;});
