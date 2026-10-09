// Render labelled corrective perturbations of MIT Enrico images through Obscura.
// These are synthetic defect labels, distinct from UICrit human annotations.
import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import crypto from 'node:crypto';
import {chromium} from 'playwright';
import {startObscura} from './c13_render.mjs';
const root=process.cwd(),base=path.join(root,'.agent_control/c13h-assets/public'),out=path.join(base,'rendered-pairs');
await fs.mkdir(out,{recursive:true});
const count=Number(process.argv[2]||400);
if(!Number.isInteger(count)||count<120)throw new Error('At least the original 120 screens are required');
const images=(await fs.readdir(path.join(base,'enrico-all'))).filter(n=>n.endsWith('.jpg')).sort().slice(0,count);
let html='';
const server=http.createServer(async(req,res)=>{
 try{if(req.url==='/'){res.setHeader('Content-Type','text/html');res.end(html);return;}
 const name=decodeURIComponent(req.url.slice(1));if(!images.includes(name)){res.writeHead(404);res.end();return;}
 res.setHeader('Content-Type','image/jpeg');res.end(await fs.readFile(path.join(base,'enrico-all',name)));}
 catch(e){res.writeHead(500);res.end(String(e));}
});
await new Promise(resolve=>server.listen(48805,'127.0.0.1',resolve));
let host,browser;const pairs=[],withheld=[];
try{
 host=await startObscura(48806,out);browser=await chromium.connectOverCDP(host.connection.endpoint,{headers:{Authorization:'Bearer '+host.connection.token}});
 const context=await browser.newContext({viewport:{width:390,height:844}}),page=await context.newPage();
 for(const [index,name] of images.entries()){
  const id=path.parse(name).name,original=path.join(out,id+'-original.png');
  const render=async(kind,file)=>{
   if(await fs.stat(file).catch(()=>null))return;
   const offset=kind==='centering'?'margin-left:140px;':'';
   const cramped=kind==='overflow'?'<div style="position:absolute;left:30px;top:210px;width:110px;height:25px;white-space:nowrap;overflow:visible;background:#eee;color:#222;font:28px Arial">Continue to the next page</div>':'';
   const washed=kind==='contrast'?'<div style="position:absolute;left:0;top:0;width:390px;height:844px;background:#fff;opacity:.90"></div>':'';
   html=`<!doctype html><html><style>body{margin:0;background:#fff;overflow:hidden}img{width:390px;height:844px;object-fit:fill;${offset}}</style><img src="/${name}" alt="Public mobile screenshot">${cramped}${washed}</html>`;
   await page.goto('http://127.0.0.1:48805/',{waitUntil:'load'});await page.waitForTimeout(40);await page.screenshot({path:file});
  };
  await render('original',original);
  for(const kind of ['contrast','centering','overflow']){
   const bad=path.join(out,id+'-'+(kind==='contrast'?'contrast-overlay':kind)+'.png');await render(kind,bad);
   const sha=async file=>crypto.createHash('sha256').update(await fs.readFile(file)).digest('hex');
   const pair={before:bad,after:original,preferred:1,group:'enrico:'+id,source:'Enrico-Obscura-synthetic',reason:'Injected '+kind+(kind==='contrast'?' overlay':'')+' defect; original is preferred only relative to this perturbation',split:index%5===0?'heldout':index%5===1?'calibration':'train',beforeSha256:await sha(bad),afterSha256:await sha(original)};
   if(pair.beforeSha256===pair.afterSha256)withheld.push({...pair,reason:'Perturbation did not change captured pixels'});
   else if(pair.split==='heldout'&&(kind==='contrast'||index>=120))withheld.push({...pair,reason:'New criterion or scene excluded from the already frozen held-out evaluation'});
   else pairs.push(pair);
  }
  if(index%20===19)console.log(JSON.stringify({screens:index+1,pairs:pairs.length}));
 }
 await context.close();await fs.writeFile(path.join(root,'proof/r11/public-render-pairs.json'),JSON.stringify({engine:'obscura',port:48806,pairs,withheld},null,2));
}finally{await browser?.close();await host?.close();await new Promise(resolve=>server.close(resolve));}
