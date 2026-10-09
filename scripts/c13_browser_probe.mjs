import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import crypto from 'node:crypto';
import {chromium} from 'playwright';
import {startObscura,activate,pointer} from './c13_render.mjs';
const root=path.resolve('scripts/evidence/c13-browser-probe');await fs.mkdir(root,{recursive:true});
const font=await fs.readFile('C:/Windows/Fonts/comic.ttf');
const html=`<!doctype html><html><head><style>@font-face{font-family:ProbeFont;src:url('/font.ttf')}p{font-family:ProbeFont;font-size:40px}button{width:200px;height:100px}a{display:block}#target{margin-top:1200px}@media(prefers-color-scheme:dark){body{background:rgb(1,2,3);color:white}}@media(prefers-reduced-motion:reduce){p{animation:none}}</style></head><body><button id="button">Probe</button><p>Font glyphs WMWMMi</p><output id="counter">0</output><a href="#target">Jump</a><div id="target">Target</div><script>window.events=[];for(const type of ['touchstart','touchend','pointerdown','pointerup','keydown','keyup','click'])document.addEventListener(type,e=>events.push({type,key:e.key,pointerType:e.pointerType,target:e.target.id,touches:e.changedTouches?[...e.changedTouches].map(t=>({x:t.clientX,y:t.clientY,id:t.identifier})):null}));button.onclick=()=>counter.textContent=String(Number(counter.textContent)+1);</script></body></html>`;
const server=http.createServer((req,res)=>{res.setHeader('content-type',req.url==='/font.ttf'?'font/ttf':'text/html');res.end(req.url==='/font.ttf'?font:html);});
await new Promise(resolve=>server.listen(48808,'127.0.0.1',resolve));const host=await startObscura(48809,root);
const report={engine:'obscura',executable:host.connection.executable};
try{
const browser=await chromium.connectOverCDP(host.connection.endpoint,{headers:{Authorization:'Bearer '+host.connection.token}});
for(const adapt of [false,true]){
 const context=await browser.newContext({viewport:{width:800,height:800},hasTouch:true});
 if(adapt){const adapter=await fs.readFile('src/grant_agent/browser_render_profile.js','utf8');await context.addInitScript({content:`(${adapter})({theme:'dark',reducedMotion:true});`});}
 const page=await context.newPage();const requests=[];page.on('request',request=>requests.push(request.url()));await page.goto('http://127.0.0.1:48808/',{waitUntil:'load'});
 const cdp=await context.newCDPSession(page);const row={requests};
 const box=await page.evaluate(()=>{const r=document.querySelector('p').getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};});
 const beforePath=path.join(root,adapt?'adapted-font-before.png':'native-font-before.png');
 const beforePixels=await page.screenshot({path:beforePath,clip:box});
 try{row.explicitFontLoad=await page.evaluate(async()=>{const results=await document.fonts.load('40px ProbeFont');return results.map(f=>({family:f.family,status:f.status}));});}catch(error){row.explicitFontLoad=error.message;}
 await page.evaluate(()=>document.querySelector('p').style.fontFamily='serif');
 const afterPath=path.join(root,adapt?'adapted-font-fallback.png':'native-font-fallback.png');
 const afterPixels=await page.screenshot({path:afterPath,clip:box});
 row.fontRaster={comparison:'actual @font-face raster versus generic serif raster at identical geometry',fontFile:'C:/Windows/Fonts/comic.ttf',fontSha256:crypto.createHash('sha256').update(font).digest('hex'),webFont:beforePath,fallback:afterPath,webFontSha256:crypto.createHash('sha256').update(beforePixels).digest('hex'),fallbackSha256:crypto.createHash('sha256').update(afterPixels).digest('hex'),pixelsChanged:!beforePixels.equals(afterPixels)};
 await page.evaluate(()=>document.querySelector('p').style.fontFamily='ProbeFont');
 try{await cdp.send('Emulation.setTouchEmulationEnabled',{enabled:true});row.touchEmulation=true;}catch(e){row.touchEmulation=e.message;}
 await page.evaluate(()=>button.focus());await page.keyboard.press('Space');
 if(adapt)await activate(page,'touch',100,50);else {await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:100,y:50}]});await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});}
 await pointer(page,'mousePressed',100,50,true);await pointer(page,'mouseReleased',100,50);await new Promise(r=>setTimeout(r,200));
 Object.assign(row,await page.evaluate(()=>({counter:counter.textContent,events,fonts:[...document.fonts].map(f=>({family:f.family,status:f.status})),fontWidth:document.querySelector('p').getBoundingClientRect().width,dark:matchMedia('(prefers-color-scheme:dark)').matches,reducedMotion:matchMedia('(prefers-reduced-motion:reduce)').matches,background:getComputedStyle(document.body).backgroundColor})));
 await page.screenshot({path:path.join(root,adapt?'adapted.png':'native.png')});report[adapt?'adapted':'native']=row;await context.close();
}await browser.close();
}finally{await host.close();await new Promise(resolve=>server.close(resolve));}
await fs.writeFile('scripts/evidence/C13-browser.json',JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
