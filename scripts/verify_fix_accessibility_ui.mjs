// Extends the existing real native navigation journey; no mock picker or backend.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';

export async function verifyAccessibility({page,tool,request,root,repo,base,renderingMechanism,buildSources,nativeBinarySha256}) {
  const sha=p=>createHash('sha256').update(fs.readFileSync(p)).digest('hex');
  const receipt={schema:'neyvia.FIXb.accessibility.v1',startedAt:new Date().toISOString(),ok:false,checks:[],pictures:[],renderingMechanism,nativeBinarySha256,boundary:'Actual production NxShell with real authenticated backend. Equivalent scoped audit of computed accessibility names, role states, ARIA references and keyboard focus at320/390/1280. No axe installation, physical native picker, installed desktop, microphone or exhaustive all-app accessibility claim.'};
  const record=(name,detail)=>{receipt.checks.push({name,ok:true,detail});console.log('PASS',name);};
  const picture=async name=>{const file=path.join(repo,'scripts/evidence/fix',`accessibility-${name}.png`);await page.screenshot({path:file});receipt.pictures.push({path:path.relative(repo,file).replaceAll('\\','/'),sha256:sha(file)});};
  const ax=await page.context().newCDPSession(page);
  const focusWarnings=[];
  const observeConsole=message=>{if(/Blocked aria-hidden|focus must not be hidden/i.test(message.text()))focusWarnings.push(message.text());};
  page.on('console',observeConsole);
  async function audit(name){
    const tree=await ax.send('Accessibility.getFullAXTree');
    const namedRoles=new Set(['button','textbox','combobox','checkbox','radio','slider','spinbutton','dialog','link','tab']);
    const nameless=tree.nodes.filter(n=>!n.ignored&&namedRoles.has(n.role?.value)&&!n.name?.value?.trim()).map(n=>({role:n.role.value,node:n.backendDOMNodeId}));
    const invalid=await page.evaluate(()=>[...document.querySelectorAll('[aria-labelledby],[aria-describedby]')].filter(e=>e.getClientRects().length).flatMap(e=>['aria-labelledby','aria-describedby'].flatMap(attr=>(e.getAttribute(attr)||'').split(/\s+/).filter(id=>id&&!document.getElementById(id)).map(id=>({tag:e.tagName,attr,id})))));
    const roles=tree.nodes.filter(n=>!n.ignored&&['radio','checkbox','tab'].includes(n.role?.value)).map(n=>({role:n.role.value,name:n.name?.value,state:n.properties?.find(p=>p.name===(n.role.value==='tab'?'selected':'checked'))?.value?.value}));
    assert.deepEqual(nameless,[],`${name} controls without accessible names`);assert.deepEqual(invalid,[],`${name} broken ARIA references`);assert.equal(roles.every(n=>n.state!==undefined),true,`${name} selectable controls without states`);
    record(name+' computed accessibility', {nodes:tree.nodes.length,nameless,invalid,roles});
  }
  async function tabs(name){
    const samples=[];const seen=new Set();
    for(let i=0;i<80;i++){
      await page.keyboard.press('Tab');
      await page.waitForTimeout(60); // Let the browser's focus scroll and1ms reduced-motion transform settle.
      const focus=await page.evaluate(()=>{const e=document.activeElement;if(!e||e===document.body)return{tag:'BODY'};let ring=false;for(let p=e;p&&p!==document.body;p=p.parentElement){const s=getComputedStyle(p);if((s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>0)||s.boxShadow!=='none')ring=true;}const r=e.getBoundingClientRect();return{tag:e.tagName,name:e.getAttribute('aria-label')||e.labels?.[0]?.textContent||e.textContent?.trim().slice(0,70)||e.title||e.placeholder,ring,visible:r.width>0&&r.height>0,inViewport:r.right>0&&r.left<innerWidth&&r.bottom>0&&r.top<innerHeight,key:e.id||e.outerHTML.slice(0,220)};});
      if(focus.tag==='BODY')break;if(seen.has(focus.key))break;seen.add(focus.key);samples.push(focus);
    }
    assert.ok(samples.length>2,`${name} Tab journey`);assert.deepEqual(samples.filter(n=>!n.ring||!n.visible||!n.inViewport),[],`${name} lost or invisible keyboard focus`);record(name+' actual Tab focus',{samples});
  }
  async function radios(name,group){
    const choices=group.getByRole('radio');const count=await choices.count();assert.ok(count>1);
    await group.locator('[role=radio][aria-checked=true]').focus();
    await page.keyboard.press('Home');await assertEventually(async()=>assert.equal(await choices.nth(0).getAttribute('aria-checked'),'true'));
    await page.keyboard.press('ArrowRight');await assertEventually(async()=>assert.equal(await choices.nth(1).getAttribute('aria-checked'),'true'));
    await page.keyboard.press('End');await assertEventually(async()=>assert.equal(await choices.nth(count-1).getAttribute('aria-checked'),'true'));
    await page.keyboard.press('ArrowDown');await assertEventually(async()=>assert.equal(await choices.nth(0).getAttribute('aria-checked'),'true'));
    assert.equal(await choices.nth(0).evaluate(e=>e===document.activeElement),true);assert.equal(await group.locator('[role=radio][tabindex="0"]').count(),1);
    record(name+' arrow/Home/End and single Tab stop',{choices:count,wraparound:true});
  }
  try{
    await page.emulateMedia({reducedMotion:'reduce'});
    if(!await page.evaluate(()=>Boolean(window.__TAURI_INTERNALS__))){const setup=await request('/api/backend',{command:'onboarding_state_command',payload:{}});assert.equal(setup.ok,true);assert.equal(setup.data.state.dismissed,true);record('Actual Skip setup persists canonical dismissal for page reloads',{dismissed:setup.data.state.dismissed,completed:setup.data.state.completed});}
    for(const width of [320,390,1280]){
      await page.setViewportSize({width,height:800});
      await page.goto(base+'/index.html?view=new');await page.getByRole('textbox',{name:'First message',exact:true}).waitFor();
      const agentBounds=await page.getByRole('radiogroup',{name:'Agent',exact:true}).getByRole('radio').evaluateAll(elements=>elements.map(e=>{const r=e.getBoundingClientRect();const label=e.lastElementChild;const range=document.createRange();range.selectNodeContents(label);const text=range.getBoundingClientRect();return{name:e.textContent.trim(),left:r.left,right:r.right,viewport:innerWidth,labelFits:text.left>=r.left&&text.right<=r.right};}));assert.equal(agentBounds.every(x=>x.left>=0&&x.right<=x.viewport&&x.labelFits),true,'Every agent choice and its whole label must fit the phone viewport');record('All agent choices and labels fit '+width,{agentBounds});
      await radios('Agent '+width,page.getByRole('radiogroup',{name:'Agent',exact:true}));
      await audit('new-chat '+width);await tabs('new-chat '+width);await picture('new-'+width);
      await page.getByRole('button',{name:'Choose a folder',exact:false}).focus();
      await tool('app.open',{app:'settings',target:'look'});await page.getByRole('region',{name:'Settings',exact:true}).waitFor();await page.getByRole('heading',{name:'Look',exact:true}).waitFor();
      if(width<760){await assertEventually(async()=>assert.equal(await page.locator('.nx-work-app').evaluate(e=>e.contains(document.activeElement)),true));const hidden=await page.locator('.nx-work-chat').evaluate(e=>({inert:e.inert,focused:e.contains(document.activeElement)}));assert.deepEqual(hidden,{inert:true,focused:false});const hiddenAx=await ax.send('Accessibility.getPartialAXTree',{objectId:(await ax.send('Runtime.evaluate',{expression:'document.querySelector(".nx-work-chat")'})).result.objectId,fetchRelatives:false});assert.equal(hiddenAx.nodes.every(n=>n.ignored),true);await page.locator('.nx-work-chat .nx-folder-trigger').evaluate(e=>e.focus());assert.equal(await page.locator('.nx-work-chat').evaluate(e=>e.contains(document.activeElement)),false);record('Focused conversation to Settings excludes hidden pane '+width,{...hidden,hiddenAxIgnored:true,programmaticHiddenFocusRefused:true});}
      assert.deepEqual(focusWarnings,[],'No hidden-focused-pane browser warning');
      await radios('Motion '+width,page.getByRole('radiogroup',{name:'Motion',exact:true}));
      const motion=await page.locator('.nx-stage').evaluate(e=>({animation:getComputedStyle(e).animationDuration,transition:getComputedStyle(e).transitionDuration,requested:matchMedia('(prefers-reduced-motion:reduce)').matches}));assert.equal(motion.requested,true);assert.equal(motion.animation,'0.001s');assert.equal(motion.transition,'0.001s');record('Rendered reduced motion '+width,motion);
      await audit('Settings '+width);await tabs('Settings '+width);await picture('settings-'+width);
      await page.keyboard.press('Control+Space');const dialog=page.getByRole('dialog',{name:'Apps and search'});await dialog.waitFor();await audit('launcher '+width);
      for(let i=0;i<12;i++){await page.keyboard.press(i===0?'Shift+Tab':'Tab');assert.equal(await dialog.evaluate(e=>e.contains(document.activeElement)),true);}
      await picture('launcher-'+width);await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});record('launcher '+width+' keyboard trap',{tabs:12});
    }
    await page.setViewportSize({width:1280,height:800});
    await page.getByRole('button',{name:'Edit system prompts',exact:true}).click();const editor=page.getByRole('dialog',{name:'Edit system prompts',exact:true});await editor.getByRole('textbox',{name:'Chat system prompt',exact:true}).waitFor();await audit('prompt editor');
    const fixture=path.join(root,'selected-system-prompt.md'),text='You are the actual selected-file agent.\nKeep café and 日本語 exactly.\n';fs.writeFileSync(fixture,'\uFEFF'+text);
    const desktop=await page.evaluate(()=>Boolean(window.__TAURI_INTERNALS__));let picker=editor.getByRole('button',{name:'Import .txt or .md',exact:true});
    if(desktop){await picker.click();picker=editor.getByRole('button',{name:'Choose a file',exact:true});await picker.waitFor();const nativeRefusal=await editor.getByRole('alert').innerText();assert.match(nativeRefusal,/picker couldn't open/);record('Native picker unavailable is an actionable explicit refusal',{nativeRefusal});}
    // A real chooser event selects a real disk file. Automation bypasses physical dialog interaction only.
    const chooserReady=page.waitForEvent('filechooser');await picker.click();const chooser=await chooserReady;await chooser.setFiles(fixture);
    const input=editor.getByLabel('Import a text or Markdown system prompt');const box=editor.getByRole('textbox',{name:'Chat system prompt',exact:true});await assertEventually(async()=>assert.equal(await box.inputValue(),text));record('Real browser file chooser opens from the production import button',{desktop,selectedDiskFile:true,physicalPickerTested:false});
    const save=editor.getByRole('button',{name:'Save role',exact:true});await save.click();await assertEventually(async()=>assert.equal(await save.isDisabled(),true));
    const library=await request('/api/backend',{command:'get_agent_prompt_library_command',payload:{}});assert.equal(library.ok,true);assert.equal(library.data.roles.chat.instructions,text);await picture('import-saved');
    await editor.getByRole('button',{name:'Close prompt editor',exact:true}).click();await editor.waitFor({state:'hidden'});await page.getByRole('button',{name:'Edit system prompts',exact:true}).click();await assertEventually(async()=>assert.equal(await editor.getByRole('textbox',{name:'Chat system prompt',exact:true}).inputValue(),text));
    record('Actual file input imports exact UTF8 bytes, saves to real owner and reopens persisted prompt',{fileSha256:sha(fixture),textSha256:createHash('sha256').update(text).digest('hex'),characters:text.length,revision:library.data.revision,physicalPickerTested:false});
    await input.setInputFiles({name:'refused.json',mimeType:'application/json',buffer:Buffer.from('{}')});await editor.getByRole('alert').waitFor();assert.match(await editor.getByRole('alert').innerText(),/Choose a .txt or .md/);assert.equal(await editor.getByRole('textbox',{name:'Chat system prompt',exact:true}).inputValue(),text);record('Invalid selected file refuses and preserves persisted prompt',{extension:'json',preserved:true});
    await picture('import-refusal');receipt.buildSources=buildSources;assert.equal(buildSources.filter(x=>x.path.startsWith('web/')).every(x=>sha(path.join(repo,x.path))===x.sha256),true,'Actual built UI source must stay unchanged');receipt.buildSourcesUnchanged=true;receipt.ok=true;
  }catch(error){receipt.error=String(error.stack??error);await picture('failure').catch(()=>{});throw error;}
  finally{page.off('console',observeConsole);receipt.focusWarnings=focusWarnings;await ax.detach();receipt.finishedAt=new Date().toISOString();receipt.sources=['web/src/neyvia/next/NxShell.jsx','web/src/neyvia/next/NxSettings.jsx','web/src/neyvia/next/NxNewChat.jsx','web/src/neyvia/NeyviaPromptEditorDialog.jsx','web/src/neyvia/NeyviaPromptEditorDialog.css','web/src/neyvia/promptFileImport.js','web/src/neyvia/next/nxPrimitives.jsx','web/src/neyvia/next/nxTokens.css','web/src/neyvia/next/nxShell.css','web/src/neyvia/next/nxVoice.css','manuals/cl/settings.cl','manuals/settings.manual.json','scripts/verify_fix_navigation_ui.mjs','scripts/verify_fix_accessibility_ui.mjs'].map(p=>({path:p,sha256:sha(path.join(repo,p))}));fs.writeFileSync(path.join(repo,'scripts/evidence/FIXb-accessibility.json'),JSON.stringify(receipt,null,2)+'\n');}
}

async function assertEventually(fn){const until=Date.now()+15000;let failure;do{try{return await fn();}catch(error){failure=error;}await new Promise(r=>setTimeout(r,100));}while(Date.now()<until);throw failure;}
