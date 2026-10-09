import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import crypto from 'node:crypto';
import {chromium} from 'playwright';
import {startObscura,pointer} from './c13_render.mjs';
import {captureMotion,diagramGeometry} from './c13_observed.mjs';
const args=Object.fromEntries(process.argv.slice(2).reduce((a,k,i,all)=>k.startsWith('--')?[...a,[k.slice(2),all[i+1]]]:a,[]));
const port=Number(args.port);if(!Number.isInteger(port)||port<48801||port>48808)throw Error('Explicit owned port required');
const out=path.resolve(args.out),html=path.resolve(args.html);await fs.mkdir(out,{recursive:true});
const bytes=await fs.readFile(html),server=http.createServer((req,res)=>{res.setHeader('Content-Type','text/html');res.end(bytes);});
await new Promise(r=>server.listen(port,'127.0.0.1',r));
let host,browser;
try{
 host=await startObscura(port+1,out);browser=await chromium.connectOverCDP(host.connection.endpoint,{headers:{Authorization:'Bearer '+host.connection.token}});
 const adapter=await fs.readFile('src/grant_agent/browser_render_profile.js','utf8');
 const hash=b=>crypto.createHash('sha256').update(b).digest('hex'),pause=ms=>new Promise(r=>setTimeout(r,ms));
 const motion=await captureMotion({browser,adapter,url:`http://127.0.0.1:${port}/`,out,fs,path,hash,pause,pointer,routeAssets:()=>async route=>{if(new URL(route.request().url()).origin===`http://127.0.0.1:${port}`)await route.continue();else await route.abort();}});
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 await context.addInitScript({content:`(${adapter})({theme:'light',reducedMotion:true,nativeColorScheme:true});`});
 const page=await context.newPage();await page.goto(`http://127.0.0.1:${port}/`);
 const svgProbe=await page.evaluate(()=>{const n=document.querySelector('svg text'),s=document.querySelectorAll('svg')[1];return {bbox:typeof n?.getBBox,bboxValue:n?.getBBox(),textLengthValue:n?.getComputedTextLength(),ctm:typeof n?.getScreenCTM,textLength:typeof n?.getComputedTextLength,rect:n?.getBoundingClientRect().toJSON(),svg:s?.getBoundingClientRect().toJSON(),canvas:document.createElement('canvas').getContext('2d').measureText('DECISION YOU CAN CHECK').width};});
 const fontProbe=await page.evaluate(()=>{
   const text='What must be true?',canvas=document.createElement('canvas').getContext('2d'),results=[];
   for(const size of [9,12,18]){
     canvas.font=size+'px sans-serif';
     const span=document.createElement('span');span.textContent=text;span.style.cssText='position:absolute;visibility:hidden;white-space:nowrap;font-family:sans-serif;font-size:'+size+'px';document.body.append(span);
     const rect=span.getBoundingClientRect();results.push({size,canvas:canvas.measureText(text).width,html:rect.width,computed:getComputedStyle(span).fontSize});span.remove();
   }
   return results;
 });
 const diagramIssues=await page.evaluate(diagramGeometry);await context.close();
 const nativeTheme=[];
 if(args['native-theme-proof']==='true')for(const scheme of ['light','dark']){
   const native=await browser.newContext({viewport:{width:800,height:600},colorScheme:scheme});
   try{const p=await native.newPage();await p.goto(`http://127.0.0.1:${port}/`);nativeTheme.push({scheme,...await p.evaluate(()=>({dark:matchMedia('(prefers-color-scheme: dark)').matches,light:matchMedia('(prefers-color-scheme: light)').matches,mode:getComputedStyle(document.getElementById('mode')).width,background:getComputedStyle(document.body).backgroundColor}))});}
   finally{await native.close();}
 }

 const report={html,html_sha256:hash(bytes),engine:'obscura',engine_executable:host.connection.executable,motion,diagramIssues,svgProbe,fontProbe,nativeTheme};
 await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));
 console.log(JSON.stringify({meaningful:motion.meaningful,themeToggle:motion.themeToggle,reducedChanged:motion.reduced?.changed,errors:motion.errors,svgProbe,diagramIssues,nativeTheme}));
}finally{await browser?.close();await host?.close();await new Promise(r=>server.close(r));}
