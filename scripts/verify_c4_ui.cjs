// Render the actual R4 artifact in both schemes and exercise its >80% branch.
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const [url,destination]=process.argv.slice(2);
if(!/^http:\/\/127\.0\.0\.1:4873[1-9]\//.test(url))throw Error('Explicit owned C4b URL required');
const luminance=rgb=>{
  const channels=rgb.slice(0,3).map(c=>{const v=c/255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4});
  return channels[0]*.2126+channels[1]*.7152+channels[2]*.0722;
};
(async()=>{
 const browser=await chromium.launch({headless:true});
 const rows=[];
 try{
  for(const scheme of ['light','dark']){
   const page=await browser.newPage({viewport:{width:520,height:440},colorScheme:scheme});
   const errors=[],external=[];
   page.on('pageerror',e=>errors.push(e.message));
   page.on('request',r=>{if(!r.url().startsWith('http://127.0.0.1:487')&&!r.url().startsWith('data:'))external.push(r.url())});
   await page.goto(url,{waitUntil:'networkidle'});
   const state=await page.evaluate(()=>{
     const meters=[...document.querySelectorAll('[role="meter"],progress')];
     const card=document.querySelector('main')||document.querySelector('article')||document.querySelector('.card');
     const rect=card?.getBoundingClientRect();
     const status=document.querySelector('[role="status"],.status,#status,#usage-status');
     const statusTops=new Set();
     if(status){
       const walker=document.createTreeWalker(status,NodeFilter.SHOW_TEXT);
       while(walker.nextNode()){
         if(!walker.currentNode.textContent.trim())continue;
         const range=document.createRange();range.selectNodeContents(walker.currentNode);
         for(const box of range.getClientRects())if(box.width&&box.height)statusTops.add(Math.round(box.top));
       }
     }
     const text=[...document.querySelectorAll('body *')].filter(e=>!['SCRIPT','STYLE'].includes(e.tagName)&&e.getClientRects().length&&e.childNodes.length&&[...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim())).map(e=>{
       const css=getComputedStyle(e);let bg=css.backgroundColor;let p=e;
       while((bg==='rgba(0, 0, 0, 0)'||bg==='transparent')&&p.parentElement){p=p.parentElement;bg=getComputedStyle(p).backgroundColor}
       return {text:e.textContent.trim().slice(0,140),color:css.color,background:bg,fontSize:css.fontSize};
     });
     return {title:document.title,body:document.body.innerText,statusLines:statusTops.size,rect:rect&&{width:rect.width,x:rect.x},
       meters:meters.map(e=>({value:Number(e.getAttribute('aria-valuenow')??e.value),label:e.getAttribute('aria-label')||e.getAttribute('aria-labelledby')||e.labels?.[0]?.textContent})),text};
   });
   const contrast=state.text.map(row=>{
      const fg=(row.color.match(/[\d.]+/g)||[]).map(Number),bg=(row.background.match(/[\d.]+/g)||[]).map(Number);
      if(fg.length<3||bg.length<3)return {...row,ratio:null};
      const a=luminance(fg),b=luminance(bg);return {...row,ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
   });
   fs.mkdirSync(destination,{recursive:true});
   await page.screenshot({path:path.join(destination,scheme+'.png')});
   // Change the values used by the artifact's own inline script, then rerun it.
   const branch=await page.evaluate(()=>{
     for(const meter of document.querySelectorAll('[role="meter"],progress')){
       meter.setAttribute('aria-valuenow','81');meter.setAttribute('value','81');
       if(meter.dataset.usage!==undefined)meter.dataset.usage='81';
       if(meter.dataset.value!==undefined)meter.dataset.value='81';
     }
     const texts=[...document.querySelectorAll('script:not([src])')].map(s=>s.textContent);
     for(const text of texts){const script=document.createElement('script');script.textContent='{'+text+'}';document.body.append(script)}
     return document.body.innerText;
   });
   await page.screenshot({path:path.join(destination,scheme+'-slow.png')});
   rows.push({scheme,state,contrast,branch,errors,external,checks:{
     width360:Math.abs((state.rect?.width||0)-360)<=1,
     horizontallyCentered:Math.abs((state.rect?.x||0)-80)<=1,
     labeledMeterValues:state.meters.length===2&&state.meters.every(m=>m.label)&&state.meters.map(m=>m.value).join(',')==='62,31',
     resetText:/1\s*h\s*48\s*min/.test(state.body)&&/Thu\s*09:00/.test(state.body),
     fineState:/fine|within|on track|looking good|comfortably|healthy|plenty/i.test(state.body),
     oneLineStatus:state.statusLines===1,
     contrast45:contrast.every(c=>c.ratio!==null&&c.ratio>=4.5),
     slowDownBranch:/slow|nearing|pause|pace|limit.*close/i.test(branch)&&branch!==state.body,
     selfContained:external.length===0,consoleClean:errors.length===0}});
   await page.close();
  }
 }finally{await browser.close()}
 const receipt={url,rows,passed:rows.every(r=>Object.values(r.checks).every(Boolean)),
   limitations:['Branch probe changes DOM meter inputs then executes the original inline script; static literals are not rewritten','Contrast evaluated on text foreground and nearest opaque ancestor background']};
 fs.writeFileSync(path.join(destination,'receipt.json'),JSON.stringify(receipt,null,2));
 console.log(JSON.stringify({passed:receipt.passed,checks:rows.map(r=>({scheme:r.scheme,...r.checks}))}));
 process.exitCode=receipt.passed?0:1;
})().catch(e=>{console.error(e);process.exitCode=1});
