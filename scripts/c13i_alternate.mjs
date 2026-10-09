import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import crypto from 'node:crypto';
import {chromium} from 'playwright';
import {startObscura} from './c13_render.mjs';
const args=Object.fromEntries(process.argv.slice(2).reduce((r,a,i,v)=>a.startsWith('--')?[...r,[a.slice(2),v[i+1]]]:r,[]));
const port=Number(args.port),enginePort=Number(args['engine-port']);
if(![port,enginePort].every(p=>p>=48801&&p<=48808)||port===enginePort)throw Error('Two distinct assigned page ports required');
const html=await fs.readFile(args.html),out=args.out;await fs.mkdir(out,{recursive:true});
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const report={engine:'obscura',scope:'alternate-destination-keyboard-probe',html_sha256:hash(html),screenshots:[],variants:[{controls:[{id:'#filing-pad',modes:[]}]}]};
const server=http.createServer((req,res)=>{res.setHeader('Content-Type','text/html');res.end(html);});
await new Promise(r=>server.listen(port,'127.0.0.1',r));const host=await startObscura(enginePort,out);let browser;
try{
 browser=await chromium.connectOverCDP(host.connection.endpoint,{headers:{Authorization:'Bearer '+host.connection.token}});
 const adapter=await fs.readFile('src/grant_agent/browser_render_profile.js','utf8');
 for(const [destination,direction] of [['Check again','ArrowUp'],['Discard sample','ArrowDown']]){
  const context=await browser.newContext({viewport:{width:390,height:844},hasTouch:true});
  try{
   await context.addInitScript({content:`(${adapter})({theme:'dark',reducedMotion:true});`});
   const page=await context.newPage();await page.goto(`http://127.0.0.1:${port}/`,{waitUntil:'load'});
   await page.evaluate(()=>{const n=document.getElementById('filing-pad');n.scrollIntoView({block:'center'});n.focus();});
   const before=await page.evaluate(()=>document.getElementById('filing-status').textContent);
   const keys=['Space',direction,'Enter'];for(const key of keys)await page.keyboard.press(key);
   await new Promise(r=>setTimeout(r,650));const after=await page.evaluate(()=>document.getElementById('filing-status').textContent);
   const effect=after.includes('filed: '+destination)&&before!==after;
   report.variants[0].controls[0].modes.push({mode:'keyboard',destination,keyboardInput:keys,effect,before,assertion:{text:after}});
   const file=path.join(out,destination==='Check again'?'check-again.png':'discard.png');
   const pixels=await page.screenshot({path:file,timeout:15000});report.screenshots.push({path:file,sha256:hash(pixels),destination});
  }finally{await context.close();}
 }
 report.passed=report.variants[0].controls[0].modes.every(m=>m.effect);
}finally{await browser?.close();await host.close();await new Promise(r=>server.close(r));}
report.scriptSha256=hash(await fs.readFile(new URL(import.meta.url)));await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({passed:report.passed,out}));
