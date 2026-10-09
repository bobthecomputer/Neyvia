'use strict';
// Real typed host API -> new engine context -> page CSS and matchMedia.
const fs=require('node:fs'),http=require('node:http'),assert=require('node:assert/strict');
const [p,f,out]=process.argv.slice(2),port=Number(p),fixturePort=Number(f);
if([port,fixturePort].some(x=>!Number.isInteger(x)||x<48721||x>48729)||port===fixturePort||!out||fs.existsSync(out))throw Error('Explicit owned distinct ports and fresh receipt required');
const base=`http://127.0.0.1:${port}`,report={schema:'neyvia.C2g.typed-preferences@1',ports:[port,fixturePort],startedAt:new Date().toISOString(),checks:[],calls:[]};let cookie,tab,server;
const save=()=>fs.writeFileSync(out,JSON.stringify(report,null,2)+'\n');
async function call(op,args={}){const r=await fetch(base+'/api/ui/browser',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:JSON.stringify({op,args})}),v=await r.json();report.calls.push({op,args,http:r.status,response:v});save();return {http:r.status,...v};}
function check(name,value,detail){report.checks.push({name,passed:!!value,detail});save();assert.ok(value,name);}
(async()=>{
 const r=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});cookie=r.headers.get('set-cookie').split(';')[0];
 await call('headless.stop');
 const bad=await call('headless.start',{port:48723,colorScheme:'secret-mode'});check('Unsupported preference refused before engine launch',bad.http===400,bad);
 const started=await call('headless.start',{port:48723,allowLocalFixtures:true,allowPublicResources:true,colorScheme:'dark',reducedMotion:'reduce'});check('Typed preferences reported by live engine',started.preferences?.colorScheme==='dark'&&started.preferences?.reducedMotion==='reduce',started);
 server=http.createServer((req,res)=>{res.setHeader('Content-Type','text/html');res.end('<!doctype html><style>#mode{width:100px}#motion{width:100px}@media(prefers-color-scheme:dark){#mode{width:240px}}@media(prefers-reduced-motion:reduce){#motion{width:40px}}</style><div id="mode"></div><div id="motion"></div><output></output><script>document.querySelector("output").textContent="dark="+matchMedia("(prefers-color-scheme:dark)").matches+";reduce="+matchMedia("(prefers-reduced-motion:reduce)").matches+";css="+getComputedStyle(document.querySelector("#mode")).width+","+getComputedStyle(document.querySelector("#motion")).width</script>');});await new Promise(r=>server.listen(fixturePort,'127.0.0.1',r));
 tab=(await call('tab.open',{url:`http://127.0.0.1:${fixturePort}`,engine:'obscura'})).tabId;
 const observed=await call('observe',{tabId:tab});check('Typed API reaches actual CSS and JavaScript preferences',observed.text?.includes('dark=true;reduce=true;css=240px,40px'),observed);
 const change=await call('headless.start',{port:48723,colorScheme:'light'});check('Connected preferences cannot silently change',change.http!==200&&change.error?.code==='runtime_connected',change);
 report.ok=true;
})().catch(e=>{report.ok=false;report.error=e.stack;process.exitCode=1;}).finally(async()=>{
 if(tab)await call('tab.close',{tabId:tab});if(server)await new Promise(r=>server.close(r));await call('headless.stop');
 const restored=await call('headless.start',{port:48723,allowLocalFixtures:true,allowPublicResources:true,colorScheme:'light',reducedMotion:'reduce'});report.restored=restored.ok;report.finishedAt=new Date().toISOString();save();console.log(JSON.stringify({ok:report.ok,checks:report.checks.map(c=>({name:c.name,passed:c.passed})),error:report.error,restored:report.restored}));
});
