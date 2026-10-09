// One real, bounded model request. Run explicitly; this is not part of unit tests.
import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
const base=process.env.NEYVIA_PROOF_BASE||'http://127.0.0.1:4173';
const dir=path.resolve(process.env.NEYVIA_PROOF_DIR||'proof/product-polish-20260910/activity');await mkdir(dir,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const context=await browser.newContext({viewport:{width:1280,height:900}});
const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
let previousCheckpoint,proofConversation;
async function continuity(command,payload){const res=await context.request.post(base+'/api/backend',{data:{command,payload}});assert.equal(res.status(),200);const value=await res.json();assert.equal(value.ok,true);return value.data;}
try {
 if(process.env.NEYVIA_PROOF_LOGIN){const r=await context.request.post(base+'/api/auth/login',{data:JSON.parse(process.env.NEYVIA_PROOF_LOGIN)});assert.equal(r.status(),200);}
 previousCheckpoint=await continuity('get_task_continuity_command',{deviceId:'product-polish-proof-reader'});
 await page.goto(base+'/control?mode=agent&surface=agent');
 await page.getByRole('textbox',{name:'Command Neyvia'}).waitFor();
 await page.waitForFunction(()=>[...document.querySelectorAll('[aria-label="Select runtime"] option')].some(o=>o.value==='gptme'),{timeout:30000});
 await page.getByRole('button',{name:'Select Model',exact:true}).click();
 await page.getByRole('dialog',{name:'Model options'}).getByRole('option',{name:'GPT-5.6 Luna gpt-5.6-luna',exact:true}).click();
 await page.getByRole('slider',{name:/Reasoning effort/}).fill('2');
 await page.getByRole('combobox',{name:'Select runtime'}).selectOption('neyvia-agent');
 // Check the visible route; never substitute another model for this proof.
 assert.match(await page.locator('.fluxos-composer').innerText(),/GPT-5\.6 Luna/);
 assert.equal(await page.getByRole('slider',{name:/Reasoning effort/}).inputValue(),'2');
 await page.getByRole('textbox',{name:'Command Neyvia'}).fill('UI verification only: reply with exactly "Ready." Do not use tools or change files.');
 await page.getByRole('button',{name:'Run composer draft'}).click();
 const thinking=page.locator('[data-agent-thinking="true"]');
 await thinking.waitFor();
 proofConversation=new URL(page.url()).searchParams.get('chatSessionId');
 assert.match(await thinking.innerText(),/Thinking/);
 assert.equal(await page.locator('.fluxos-message-trace').count(),0);
 await page.screenshot({path:path.join(dir,'thinking.png')});
 await page.locator('.neyvia-run-receipt').waitFor({timeout:210000});
 await thinking.waitFor({state:'detached'});
 const receipt=page.locator('.neyvia-run-receipt');
 assert.equal(await receipt.getAttribute('data-run-phase'),'success');
 assert.match(await page.locator('.role-assistant').innerText(),/Ready\./);
 await page.screenshot({path:path.join(dir,'completed.png')});
 await receipt.locator(':scope > summary').click();
 const source=receipt.locator(':scope > .neyvia-run-body > .neyvia-run-source');
 await source.locator(':scope > summary').click();
 const data=JSON.parse(await source.locator('pre').innerText());
 assert.match(String(data.model),/luna/i);assert.equal(data.effort,'medium');
 assert.deepEqual(errors,[]);
 await writeFile(path.join(dir,'receipt.json'),JSON.stringify({at:new Date().toISOString(),base,url:page.url(),requestId:data.requestId||data.id,model:data.model,effort:data.effort,runtime:data.runtime,status:data.status,durationMs:data.durationMs,checks:['Visible Thinking before any reasoning trace','Activity stops on completion','Real Luna medium response and receipt'],errors},null,2));
 console.log('Real active -> completed request verified: '+page.url());
}catch(error){await page.screenshot({path:path.join(dir,'failed.png')});throw new Error(String(error?.message||error).split('\nCall log:')[0]);}
finally{
 try {
  if(previousCheckpoint?.sharedLatest?.conversationId && proofConversation){
   const current=await continuity('get_task_continuity_command',{deviceId:'product-polish-proof-reader'});
   if(current.sharedLatest?.conversationId===proofConversation){
    const restored=await continuity('save_task_continuity_command',{deviceId:'product-polish-proof-restore',conversationId:previousCheckpoint.sharedLatest.conversationId,draft:previousCheckpoint.sharedLatest.draft??'',expectedRevision:current.revision});
    // A concurrent user update wins instead of being overwritten by proof cleanup.
    console.log(restored.status==='conflict'?'Preserved concurrent task checkpoint.':'Restored previous task checkpoint.');
   }
  }
 }finally{await browser.close();}
}
