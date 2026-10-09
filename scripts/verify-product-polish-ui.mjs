import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
const base=process.env.NEYVIA_PROOF_BASE||'http://127.0.0.1:4173';
const conversation=process.env.NEYVIA_PROOF_CONVERSATION||'conversation_41560ec27acf41a78afc2ef93d5e87e8';
const dir=path.resolve(process.env.NEYVIA_PROOF_DIR||'proof/product-polish-20260910/journeys');await mkdir(dir,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const checks=[],errors=[];let currentPage;
let checkpointContext,previousCheckpoint;
async function continuity(command,payload){const res=await checkpointContext.request.post(base+'/api/backend',{data:{command,payload}});assert.equal(res.status(),200);const value=await res.json();assert.equal(value.ok,true);return value.data;}
async function check(name,fn){await fn();checks.push(name);console.log(name);}
async function shot(page,name){await page.screenshot({path:path.join(dir,name+'.png')});}
async function open(context,surface,params='') {const p=await context.newPage();currentPage=p;p.on('pageerror',e=>errors.push(e.message));await p.goto(`${base}/control?mode=agent&surface=${surface}${params}`);await p.locator('[data-neyvia-shell="true"]').waitFor({timeout:40000});return p;}
try{
 checkpointContext=await browser.newContext();
 if(process.env.NEYVIA_PROOF_LOGIN){const res=await checkpointContext.request.post(base+'/api/auth/login',{data:JSON.parse(process.env.NEYVIA_PROOF_LOGIN)});assert.equal(res.status(),200);}
 previousCheckpoint=await continuity('get_task_continuity_command',{deviceId:'product-polish-ui-reader'});
 for(const [name,width,height] of [['desktop',1280,900],['phone',390,844]]){
 const context=await browser.newContext({viewport:{width,height},reducedMotion:'reduce'});
 if(process.env.NEYVIA_PROOF_LOGIN){const res=await context.request.post(base+'/api/auth/login',{data:JSON.parse(process.env.NEYVIA_PROOF_LOGIN)});assert.equal(res.status(),200);}
 const p=await open(context,'agent',`&agentScene=run&chatSessionId=${conversation}`);
 await p.getByText('How we work',{exact:true}).waitFor({timeout:30000});
 await p.locator('.neyvia-run-receipt').last().waitFor();
 await check(name+': saved conversation resumes with compact receipts',async()=>{
   assert.equal(await p.locator('.neyvia-run-receipt[open]').count(),0);
   assert.equal(await p.locator('.fluxos-message-provenance').filter({hasText:'Agent response'}).count(),0);
   assert.equal(await p.locator('.neyvia-message-body p').last().evaluate(e=>getComputedStyle(e).whiteSpace),'normal');
   await p.locator('.fluxos-thread').evaluate(e=>e.scrollTop=e.scrollHeight);
   await shot(p,name+'-conversation');
 });
 await check(name+': run details and source receipt work by keyboard',async()=>{
   const receipt=p.locator('.neyvia-run-receipt').last();
   const summary=receipt.locator(':scope > summary');await summary.focus();await summary.press('Enter');
   assert.equal(await receipt.getAttribute('open'),'');
   assert.equal(await receipt.locator('.neyvia-run-route').isVisible(),true);
   assert.equal(await receipt.getByText('Model response',{exact:true}).count(),0);
   await summary.scrollIntoViewIfNeeded();await shot(p,name+'-run-details');
   const source=receipt.locator(':scope > .neyvia-run-body > .neyvia-run-source > summary');await source.focus();await source.press('Enter');
   assert.equal(await receipt.locator(':scope > .neyvia-run-body > .neyvia-run-source > pre').isVisible(),true);
   await source.press('Enter');await summary.focus();await summary.press('Enter');
 });
 const failed=p.locator('[data-runtime-error="true"]').first();
 if(await failed.count())await check(name+': real failed turn keeps recovery actions',async()=>{
   await failed.scrollIntoViewIfNeeded();assert(await failed.getByRole('button',{name:'Restore message to draft',exact:true}).isVisible());
   assert.equal(await failed.locator('[data-run-phase="error"]').count(),1);await shot(p,name+'-failed-turn');
 });
 await check(name+': task preferences open and close',async()=>{
   await p.getByText('How we work',{exact:true}).click();
   await p.getByRole('checkbox',{name:'Keep reusable experience after work'}).waitFor();await shot(p,name+'-task-preferences');
   await p.getByText('How we work',{exact:true}).click();
 });
 await check(name+': add menu and preview open',async()=>{
   await p.getByRole('button',{name:'Add context or action',exact:true}).click();await shot(p,name+'-tools');
   await p.locator('.fluxos-composer-plus-menu').getByText('Preview',{exact:true}).click();
   const panel=p.locator('[data-agent-preview-window="true"]');await panel.waitFor();
   await shot(p,name+'-preview');if(name==='desktop')await panel.getByRole('button',{name:'Expand',exact:true}).click();
   assert.equal(await panel.getAttribute('role'),'dialog');await shot(p,name+'-preview-expanded');
   await panel.getByRole('button',{name:'Close',exact:true}).click();assert.equal(await panel.count(),0);
 });
 assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await p.close();
 const home=await open(context,'agent');await home.locator('[data-neyvia-chat-starters]').waitFor();
 await check(name+': orchestration shares the chat start',async()=>{
   await home.getByRole('button',{name:'Orchestrate',exact:true}).click();
   assert(await home.locator('[data-neyvia-chat-starters]').isVisible());await home.getByRole('button',{name:'Add agent',exact:true}).waitFor();await shot(home,name+'-orchestration');
 });
 await home.close();
 const market=await open(context,'lab');
 await check(name+': Marketplace opens and lists apps',async()=>{
   await market.getByRole('button',{name:'Marketplace',exact:true}).last().click();await market.locator('[data-neyvia-marketplace]').waitFor();
   await market.waitForFunction(()=>document.querySelector('[data-neyvia-marketplace]')?.dataset.state!=='loading');
   await shot(market,name+'-marketplace');await market.getByRole('button',{name:'Close Marketplace',exact:true}).click();
 });
 await market.close();
 await context.close();
 }
 assert.deepEqual(errors,[],'No uncaught browser errors');
}catch(error){if(currentPage&&!currentPage.isClosed()){await shot(currentPage,'failed');await writeFile(path.join(dir,'failed-state.txt'),await currentPage.locator('body').innerText());}throw new Error(String(error?.message||error).split('\nCall log:')[0]);}
finally{
 try {
  if(previousCheckpoint?.sharedLatest?.conversationId){
   const current=await continuity('get_task_continuity_command',{deviceId:'product-polish-ui-reader'});
   if(current.sharedLatest?.conversationId===conversation)await continuity('save_task_continuity_command',{deviceId:'product-polish-ui-restore',conversationId:previousCheckpoint.sharedLatest.conversationId,draft:previousCheckpoint.sharedLatest.draft??'',expectedRevision:current.revision});
  }
 }finally{await writeFile(path.join(dir,'checks.json'),JSON.stringify({at:new Date().toISOString(),base,conversation,checks,errors,boundary:'Real saved runtime conversation and live UI. No model inference or external app execution. Phone viewport is emulated.'},null,2));await browser.close();}
}
