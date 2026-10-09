import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
const base=process.env.NEYVIA_PROOF_BASE||'http://127.0.0.1:4173';
const dir=path.resolve(process.env.NEYVIA_PROOF_DIR||'proof/product-polish-20260910/studios');
await mkdir(dir,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const checks=[],errors=[],artifacts=[],networkFailures=[];
let page;
async function check(name,fn){await fn();checks.push(name);console.log(name);}
async function shot(name){await page.screenshot({path:path.join(dir,name+'.png')});}
async function exported(button,name){const promise=page.waitForEvent('download');await button.click();const download=await promise;const file=path.join(dir,name);await download.saveAs(file);const bytes=await readFile(file);assert(bytes.length>0);artifacts.push({file:name,bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex')});return bytes;}
const audio=Buffer.alloc(44+16000*2*5);audio.write('RIFF');audio.writeUInt32LE(audio.length-8,4);audio.write('WAVEfmt ',8);audio.writeUInt32LE(16,16);audio.writeUInt16LE(1,20);audio.writeUInt16LE(1,22);audio.writeUInt32LE(16000,24);audio.writeUInt32LE(32000,28);audio.writeUInt16LE(2,32);audio.writeUInt16LE(16,34);audio.write('data',36);audio.writeUInt32LE(audio.length-44,40);for(let i=0;i<80000;i++)audio.writeInt16LE(Math.round(1800*Math.sin(i/16000*2*Math.PI*440)*(.5+.5*Math.sin(i/16000*3))),44+i*2);
const svg=Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="#182337"/><circle cx="400" cy="240" r="150" fill="#7999cd"/><path d="M80 340L240 80L400 340Z" fill="#eedcb3"/><text x="32" y="442" font-family="sans-serif" font-size="24" fill="white">Neyvia · image interaction fixture</text></svg>');
try{
for(const [viewport,width,height] of [['desktop',1280,900],['phone',390,844]]){
 const context=await browser.newContext({viewport:{width,height},reducedMotion:'reduce'});
 if(process.env.NEYVIA_PROOF_LOGIN){const r=await context.request.post(base+'/api/auth/login',{data:JSON.parse(process.env.NEYVIA_PROOF_LOGIN)});assert.equal(r.status(),200);}
 page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));page.on('requestfailed',r=>networkFailures.push({path:new URL(r.url()).pathname,error:r.failure()?.errorText}));
 async function open(surface){await page.goto(`${base}/control?mode=agent&surface=${surface}`);await page.locator('[data-neyvia-shell]').waitFor();}
 await open('ios-studio');
 await check(viewport+': device runs a real app in both orientations',async()=>{
  await page.getByRole('button',{name:'Connect a running app'}).click();
  await page.getByRole('textbox',{name:'Running app URL'}).fill(base+'/api/browser-click-probe');
  await page.getByRole('button',{name:'Open app',exact:true}).click();
  const app=page.frameLocator('.neyvia-device-screen iframe');
  await app.getByRole('button',{name:'Send bridge click'}).click();
  assert.match(await app.getByRole('status').innerText(),/: 1$/);
  assert.equal(await app.locator('body').evaluate(()=>innerWidth),390);
  await page.locator('.neyvia-device-preview').scrollIntoViewIfNeeded();await shot(viewport+'-device-portrait');
  await page.getByRole('button',{name:'Use landscape orientation'}).click();
  assert.equal(await app.locator('body').evaluate(()=>innerWidth),780);
  await page.getByRole('button',{name:'Expand device preview'}).click();
  await app.getByRole('button',{name:'Send bridge click'}).click();
  assert.match(await app.getByRole('status').innerText(),/: 2$/);await shot(viewport+'-device-landscape');
  await page.getByRole('button',{name:'Restore device preview'}).click();
  await page.getByRole('button',{name:'Reload app'}).click();
  await app.getByRole('status').filter({hasText:/: 0$/}).waitFor();
 });
 await open('lumaforge');
 await check(viewport+': image upload, rotation and PNG export',async()=>{
  await page.locator('[data-studio-file-input="lumaforge"]').setInputFiles({name:'polish-fixture.svg',mimeType:'image/svg+xml',buffer:svg});
  await page.getByRole('status').filter({hasText:/Loaded/}).waitFor();
  await page.getByRole('button',{name:'Rotate',exact:true}).click();
  const result=await exported(page.getByRole('button',{name:'Export PNG',exact:true}),viewport+'-image.png');
  assert.equal(result.readUInt32BE(16),480);assert.equal(result.readUInt32BE(20),640);
  await shot(viewport+'-image-studio');
  await page.locator('[data-studio-file-input="lumaforge"]').setInputFiles({name:'invalid.png',mimeType:'image/png',buffer:Buffer.from('invalid image fixture')});
  await page.getByRole('status').filter({hasText:/could not be rendered/}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Export PNG',exact:true}).isEnabled(),false);
 });
 await open('cueledger');
 await check(viewport+': audio playback, seek, cue and export',async()=>{
  await page.locator('[data-studio-file-input="cueledger"]').setInputFiles({name:'polish-tone.wav',mimeType:'audio/wav',buffer:audio});
  await page.getByRole('button',{name:'Play audio'}).click();
  await page.getByRole('button',{name:'Pause audio'}).click();
  await page.getByRole('slider',{name:'Audio playhead'}).fill('1.25');
  await page.getByRole('textbox',{name:'Cue note'}).fill('Verification cue at the selected playhead');
  await page.getByRole('button',{name:'Add cue',exact:true}).click();
  const sheet=JSON.parse(await exported(page.getByRole('button',{name:'Export cue sheet',exact:true}),viewport+'-cues.json'));
  assert.equal(sheet.cues.length,1);assert.equal(sheet.cues[0].time,1.25);assert.equal(sheet.source.durationSeconds,5);
  await shot(viewport+'-audio-studio');
 });
 await open('citecraft');
 await check(viewport+': source, linked claim, persistence and notes export',async()=>{
  await page.getByRole('textbox',{name:'Source title',exact:true}).fill('Local interaction fixture');
  await page.getByRole('textbox',{name:'Source URL',exact:true}).fill(base+'/api/browser-click-probe');
  await page.getByRole('textbox',{name:'Source note'}).fill('Click increments the count inside the served app.');
  await page.getByRole('button',{name:'Add source',exact:true}).click();
  assert.equal(await page.locator('.neyvia-research-list li small').innerText(),'Source 1');
  await page.getByRole('textbox',{name:'Research claim'}).fill('The embedded app receives clicks.');
  await page.getByRole('textbox',{name:'Sources that back it'}).fill('1');
  await page.getByRole('button',{name:'Add claim',exact:true}).click();
  await page.reload();await page.locator('.neyvia-claim-list li').waitFor();
  const notes=(await exported(page.getByRole('button',{name:'Export notes',exact:true}),viewport+'-research.md')).toString();
  assert(notes.includes('The embedded app receives clicks.'));assert(notes.includes('Sources: [1]'));assert(notes.includes('### [1] Local interaction fixture'));await shot(viewport+'-research-studio');
 });
 if(process.env.NEYVIA_VIDEO_FIXTURE){
  await open('frameweave');
  await check(viewport+': video playback, cut and frame export',async()=>{
   await page.locator('[data-studio-file-input="frameweave"]').setInputFiles(path.resolve(process.env.NEYVIA_VIDEO_FIXTURE));
   await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2);
   await page.getByRole('button',{name:'Play video'}).click();
   await page.getByRole('button',{name:'Pause video'}).click();
   await page.getByLabel('Cut in',{exact:true}).fill('1');await page.getByLabel('Cut out',{exact:true}).fill('3');
   const edit=JSON.parse(await exported(page.getByRole('button',{name:'Export edit decision',exact:true}),viewport+'-edit.json'));
   assert.equal(edit.selectedDurationSeconds,2);
   const frame=await exported(page.getByRole('button',{name:'Capture frame',exact:true}),viewport+'-frame.png');
   assert.equal(frame.readUInt32BE(16),640);await shot(viewport+'-video-studio');
  });
 }
 await open('aegis-range');
 await check(viewport+': assessment scope controls and report export',async()=>{
  assert.equal(await page.getByRole('button',{name:'Record finding',exact:true}).isEnabled(),false);
  await page.getByLabel('Authorized target',{exact:true}).fill('Disposable local UI fixture');
  await page.getByLabel('Exact scope',{exact:true}).fill('Form entry and JSON export only. No network testing.');
  await page.getByRole('checkbox',{name:'I confirm this target is authorized for the assessment.'}).check();
  await page.getByRole('textbox',{name:'Finding title'}).fill('Report export interaction verified');
  await page.getByRole('combobox',{name:'Finding severity'}).selectOption('informational');
  await page.getByRole('textbox',{name:'Finding evidence'}).fill('Disposable test record; no security claim.');
  await page.getByRole('button',{name:'Record finding',exact:true}).click();
  const report=JSON.parse(await exported(page.getByRole('button',{name:'Export report',exact:true}),viewport+'-assessment.json'));
  assert.equal(report.findings.length,1);assert.equal(report.authorizationConfirmed,true);await shot(viewport+'-assessment-studio');
 });
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await context.close();
}
assert.deepEqual(errors,[]);
}catch(error){if(page&&!page.isClosed()){await shot('failed');await writeFile(path.join(dir,'failed-state.txt'),await page.locator('body').innerText());await writeFile(path.join(dir,'failed-network.json'),JSON.stringify({url:page.url(),networkFailures},null,2));}throw new Error(String(error?.message||error).split('\nCall log:')[0]);}
finally{await writeFile(path.join(dir,'checks.json'),JSON.stringify({at:new Date().toISOString(),base,checks,errors,artifacts,boundary:'Real UI interactions with disposable local media and source fixtures. Web device canvas, not native iOS simulation. No external generation provider exercised.'},null,2));await browser.close();}
