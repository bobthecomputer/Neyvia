import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
const base=process.env.NEYVIA_PROOF_BASE||'http://127.0.0.1:4173';
const dir=path.resolve(process.env.NEYVIA_PROOF_DIR||'proof/product-polish-20260910/startup');await mkdir(dir,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const context=await browser.newContext({viewport:{width:1280,height:900}});
const page=await context.newPage();const checks=[];
try {
 if(process.env.NEYVIA_PROOF_LOGIN){const r=await context.request.post(base+'/api/auth/login',{data:JSON.parse(process.env.NEYVIA_PROOF_LOGIN)});assert.equal(r.status(),200);}
 const html=await context.request.get(base+'/control');assert.equal(html.headers()['cache-control'],'no-store');
 const markup=await html.text();const asset=markup.match(/src="\.\/assets\/(index-[^"]+\.js)"/)[1];
 const bundle=await context.request.get(base+'/assets/'+asset);assert.equal(bundle.status(),200);assert.match(bundle.headers()['cache-control'],/immutable/);
 const missing=await context.request.get(base+'/assets/missing-12345678.js');assert.equal(missing.status(),404);assert.match(missing.headers()['content-type'],/json/);
 checks.push('Fresh entry HTML, immutable fingerprinted bundles and explicit missing-asset 404');
 await page.route('**/assets/index-*.js',route=>route.abort('failed'));
 await page.goto(base+'/control');
 await page.getByRole('button',{name:'Reload workspace',exact:true}).waitFor();
 assert.match(await page.locator('#neyvia-startup').innerText(),/hasn’t opened/);
 await page.screenshot({path:path.join(dir,'interrupted-startup.png')});
 await page.unroute('**/assets/index-*.js');
 await page.getByRole('button',{name:'Reload workspace',exact:true}).click();
 await page.locator('[data-neyvia-shell]').waitFor({timeout:30000});
 // The splash lifts once the conversation list is on screen.
 await page.locator('#neyvia-startup').waitFor({state:'detached',timeout:15000});
 checks.push('Deliberately failed module displays recovery; Reload opens the actual workspace');
 await page.goto(base+'/control?mode=agent&surface=ios-studio');
 await page.locator('.neyvia-device-preview').waitFor();
 const entries=await page.evaluate(()=>performance.getEntriesByType('resource').filter(e=>e.name.includes('/assets/')).map(e=>({asset:new URL(e.name).pathname,transferSize:e.transferSize,decodedBodySize:e.decodedBodySize})));
 assert(entries.some(e=>e.asset.includes('vendor-tauri-')&&e.transferSize===0&&e.decodedBodySize>0),'Repeated route reuses the Tauri bundle from cache');
 await page.screenshot({path:path.join(dir,'recovered-workspace.png')});
 checks.push('Subsequent navigation reuses an unchanged bundle instead of downloading it again');
 await writeFile(path.join(dir,'checks.json'),JSON.stringify({at:new Date().toISOString(),base,checks,entries,boundary:'One intentionally intercepted startup module, followed by unmodified live UI and browser cache measurements. No inference.'},null,2));
 console.log(checks.join('\n'));
}catch(error){throw new Error(String(error?.message||error).split('\nCall log:')[0]);}
finally{try{if(process.env.NEYVIA_PROOF_LOGIN)await context.request.post(base+'/api/auth/logout',{timeout:10000}).catch(()=>{});}finally{await browser.close();}}
