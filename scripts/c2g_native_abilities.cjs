/* Exercise the actual already attached private-desktop WebView2 bridge. */
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert/strict'),crypto=require('crypto');
const repo=path.resolve(__dirname,'..'),base='http://127.0.0.1:48721',fixtureBase='http://127.0.0.1:48725',output=path.resolve(process.argv[2]||path.join(repo,'scripts/evidence/C2g-native-abilities.json'));
if(!output.startsWith(path.join(repo,'scripts','evidence')+path.sep)||fs.existsSync(output))throw Error('Fresh task evidence receipt required');
const report={schema:'neyvia.C2g.native-abilities@1',engine:'WebView2',route:'agent-private-desktop',startedAt:new Date().toISOString(),ports:[48721,48725],checks:[],calls:[],requests:[]};
let cookie='',tabId,fixture;
const sleep=ms=>new Promise(r=>setTimeout(r,ms)),save=()=>fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');
async function call(op,args={}){const r=await fetch(base+'/api/ui/browser',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:JSON.stringify({op,args}),signal:AbortSignal.timeout(35000)});const v=await r.json();report.calls.push({op,status:r.status,response:v});assert.equal(v.ok,true,JSON.stringify(v));return v;}
async function done(row){return row.actionId?await call('wait',{actionId:row.actionId,timeoutMs:30000}):row;}
async function observe(){const row=await done(await call('observe',{tabId}));return row.result?.observation||row;}
async function eventual(fn,timeout=20000){const deadline=Date.now()+timeout;while(Date.now()<deadline){const v=await fn();if(v)return v;await sleep(30);}throw Error('Native expected state did not arrive');}
function check(name,ok,detail){report.checks.push({name,ok:!!ok,detail});save();assert.ok(ok,name);}
const fontName=fs.readdirSync(path.join(repo,'.agent_control/C2f/build/assets')).find(n=>/^geist-latin-wght-normal-.*\.woff2$/.test(n));
const font=fs.readFileSync(path.join(repo,'.agent_control/C2f/build/assets',fontName));
const html=`<!doctype html><html><head><title>Actual private browser abilities</title><style>@font-face{font-family:C2gProof;src:url('/proof.woff2')}body{font:22px C2gProof;background:#102030;color:white;padding:24px}button,[role=button],[draggable=true]{padding:12px;margin:12px;background:#304860}a{color:#ade0ca}#target{margin-top:1200px}#status{position:fixed;bottom:10px;right:10px;background:#102030}</style></head><body><h1>Actual private browser abilities</h1><p id=events>Stream pending</p><div draggable=true id=source ondragstart="event.dataTransfer.setData('text/plain','actual native payload')">Drag native item</div><div role=button id=drop ondragover="event.preventDefault()" ondrop="document.getElementById('dropresult').textContent=event.dataTransfer.getData('text/plain')">Drop native item here</div><p id=dropresult>Drop pending</p><a href=#target>Jump to native target</a><h2 id=target>Native fragment target</h2><p id=status>Font pending</p><script>window.sameDocument='kept';const events=new EventSource('/events');let messages=[];events.onmessage=e=>{messages.push(e.data);document.getElementById('events').textContent=messages.join('|');if(messages.length===2)events.close();};document.fonts.load('22px C2gProof').then(f=>{document.getElementById('status').textContent='Font: '+f.map(x=>x.status).join(',')+' | Automation: '+navigator.webdriver;});</script></body></html>`;
async function main(){
 fixture=http.createServer((q,r)=>{report.requests.push({path:q.url,at:Date.now()});if(q.url==='/events'){r.writeHead(200,{'Content-Type':'text/event-stream','Cache-Control':'no-cache'});setTimeout(()=>{r.write('data: first actual native chunk\n\n');report.firstChunkAt=Date.now();},150);setTimeout(()=>{r.write('data: second actual native chunk\n\n');report.secondChunkAt=Date.now();},2000);setTimeout(()=>{r.end();report.streamClosedAt=Date.now();},4500);}else if(q.url==='/proof.woff2'){r.writeHead(200,{'Content-Type':'font/woff2'});r.end(font);}else{r.writeHead(200,{'Content-Type':'text/html'});r.end(html);}});
 await new Promise((r,j)=>{fixture.once('error',j);fixture.listen(48725,'127.0.0.1',r);});
 const login=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});assert.equal(login.status,200);cookie=login.headers.get('set-cookie').split(';')[0];
 const state=await call('state');assert.equal(state.runtime.connected,true);
 tabId=(await done(await call('tab.open',{url:fixtureBase+'/',engine:'webview2'}))).tabId;
 let obs=await eventual(async()=>{const o=await observe();return o.text.includes('first actual native chunk')?o:false;});
 check('Native SSE first chunk reaches live DOM before second chunk/server close',!report.secondChunkAt&&!report.streamClosedAt,obs);
 obs=await eventual(async()=>{const o=await observe();return o.text.includes('second actual native chunk')&&o.text.includes('Font: loaded')?o:false;});
 check('Native real web font loaded and explicit automation visible',obs.text.includes('Font: loaded')&&obs.automation.webdriver===true&&obs.automation.userAgent.includes('NeyviaAgent'),obs);
 check('Native SSE chunks appear in server order',obs.text.includes('first actual native chunk|second actual native chunk'),obs.text);
 await done(await call('tab.grant',{tabId,enabled:true}));
 obs=await observe();let source=obs.elements.find(e=>e.name==='Drag native item'),drop=obs.elements.find(e=>e.name==='Drop native item here');
 assert.ok(source?.actions.includes('drag'));assert.ok(drop);
 const dragged=await done(await call('action',{tabId,revision:obs.revision,element:source.id,destination:drop.id,action:'drag',expect:{path:'/text',contains:'actual native payload'}}));
 check('Native observed drag dispatch transfers actual DataTransfer payload',dragged.result?.verification?.verified,dragged);
 obs=await observe();const link=obs.elements.find(e=>e.name==='Jump to native target');assert.ok(link);
 const linked=await done(await call('action',{tabId,revision:obs.revision,element:link.id,action:'click',expect:{path:'/url',contains:'#target'}}));
 check('Native in-page link verified with retained streamed content',linked.result?.verification?.verified&&linked.result.observation.text.includes('second actual native chunk')&&linked.result.observation.text.includes('actual native payload'),linked);
 await done(await call('layout',{tabs:[{tabId,x:0,y:0,width:1200,height:730,visible:true}]}));
 const captured=await done(await call('capture',{tabId}));const image=output.replace(/\.json$/,'.png');fs.copyFileSync(captured.result.path,image);report.capture={path:path.relative(repo,image),bytes:fs.statSync(image).size,sha256:crypto.createHash('sha256').update(fs.readFileSync(image)).digest('hex')};
 report.guard=JSON.parse(fs.readFileSync(path.join(repo,'.agent_control/C2g/private-native-48721/native-live-guard.json'),'utf8')).guard;
 check('Private native live journey guard has no owned window/input disturbance',report.guard.ok,report.guard);
}
main().catch(e=>{report.error=e.stack;process.exitCode=1;}).finally(async()=>{if(tabId)try{await done(await call('tab.close',{tabId}));}catch{}if(fixture)await new Promise(r=>fixture.close(r));report.finishedAt=new Date().toISOString();save();console.log(JSON.stringify({checks:report.checks.map(({name,ok})=>({name,ok})),error:report.error,capture:report.capture}));});
