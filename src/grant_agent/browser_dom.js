/* Shared CL projection and effect checks for WebView2 and Obscura. */
(() => {
  if (globalThis.__neyviaProjection) return;
  const selector='button,input,select,textarea,a[href],[role],[draggable=true],h1,h2,h3,table,img,canvas,svg';
  const secret=e=>e.type==='password'||/password|cc-number|cc-csc|one-time-code/.test(e.autocomplete||'');
  const disabled=e=>{if(e.disabled||e.hasAttribute('disabled')||e.getAttribute('aria-disabled')==='true')return true;try{if(e.matches(':disabled'))return true;}catch(_){}for(let p=e.parentElement;p;p=p.parentElement)if(p.matches('fieldset[disabled]')&&!Array.from(p.children).find(n=>n.tagName==='LEGEND')?.contains(e))return true;return false;};
  const readOnly=e=>!!e.readOnly||e.hasAttribute('readonly');
  const editable=e=>e.matches('textarea')||(e.matches('input')&&!['checkbox','radio','button','submit','image','reset','hidden'].includes(e.type));
  const searchEditable=e=>editable(e)&&(e.type==='search'||e.getAttribute('role')==='searchbox'||e.getAttribute('name')==='q'||/search|query|keyword/i.test([e.getAttribute('aria-label'),e.getAttribute('placeholder')].join(' ')));
  const semanticClick=e=>['button','link','checkbox','radio','switch','tab','option','menuitem','menuitemcheckbox','menuitemradio','treeitem','gridcell'].includes(e.getAttribute('role'))&&e.getAttribute('aria-readonly')!=='true';
  const actions=e=>secret(e)||disabled(e)||e.matches('input[type=hidden]')?[]:e.matches('select')?['select']:editable(e)?[...(!readOnly(e)?['fill']:[]),...(e.form||searchEditable(e)&&!readOnly(e)?['submit']:[])]:[...(e.matches('button,a,input')||semanticClick(e)?['click']:['scroll']),...(e.getAttribute('draggable')==='true'?['drag']:[])];
  // Some non-layout DOM engines return script/style source in innerText.
  // In semantic mode read only user content, retaining visible labels and values.
  const text=e=>{
    if(!e)return '';
    if(geometryRequired)return String(e.innerText??e.textContent??'');
    // Keep this linear and bounded. Calling layout/computed style for every
    // text node makes large public pages many seconds slower in Obscura.
    const chunks=[];let length=0;
    const read=n=>{
      if(length>40000)return;
      if(n.nodeType===3){const value=String(n.textContent||'').replace(/\s+/gu,' ').slice(0,40001-length);chunks.push(value);length+=value.length;return;}
      if(n.nodeType!==1||['SCRIPT','STYLE','NOSCRIPT','TEMPLATE','HEAD'].includes(n.tagName)||n.hasAttribute('hidden')||n.getAttribute('aria-hidden')==='true'||n.style?.display==='none'||n.style?.visibility==='hidden'||(n.ownerDocument!==document&&declaredHidden(n)))return;
      for(const child of Array.from(n.childNodes||[])){read(child);if(length>40000)break;}
      // Inline spans may split a single word or IPA symbol. Only block-like
      // elements introduce a separator; never invent spaces inside that word.
      if(length<40001&&['P','DIV','SECTION','ARTICLE','LI','TR','H1','H2','H3','BR'].includes(n.tagName)){chunks.push('\n');length++;}
    };read(e);return chunks.join('');
  };
  let geometryRequired=true;
  let hiddenCache=new WeakMap();
  let documentHidden=new WeakMap();
  const declaredHidden=e=>{
    if(e.style?.display==='none'||e.style?.visibility==='hidden')return true;
    const doc=e.ownerDocument;
    if(!documentHidden.has(doc)){
      const hidden=new WeakSet();
      const rules=items=>{for(const r of Array.from(items||[])){
        if(r.selectorText&&(r.style?.display==='none'||r.style?.visibility==='hidden')){try{for(const node of Array.from(doc.querySelectorAll(r.selectorText)))hidden.add(node);}catch(_){}}
        if(r.cssRules&&(!r.conditionText||doc.defaultView.matchMedia(r.conditionText).matches))rules(r.cssRules);
      }};
      for(const sheet of Array.from(doc.styleSheets||[])){try{if(!sheet.disabled)rules(sheet.cssRules);}catch(_){}}
      documentHidden.set(doc,hidden);
    }
    return documentHidden.get(doc).has(e);
  };
  const hidden=e=>{
    if(hiddenCache.has(e))return hiddenCache.get(e);
    // Obscura aliases child computed styles to parent layout slots, hiding
    // unrelated child BODY/P nodes. In semantic frames use their own rules.
    let value;
    if(!geometryRequired&&e.ownerDocument!==document)value=declaredHidden(e);
    else {const s=e.ownerDocument.defaultView.getComputedStyle(e);value=s.visibility==='hidden'||s.display==='none';}
    hiddenCache.set(e,value);return value;
  };
  const visible=e=>{const r=e.getBoundingClientRect();if((geometryRequired&&!(r.width>0&&r.height>0))||hidden(e)||e.closest('[hidden],[aria-hidden="true"]'))return false;
    if(!geometryRequired)for(let p=e.parentElement;p;p=p.parentElement){if(hidden(p))return false;}
    return true;};
  const labelText=e=>Array.from(e.childNodes||[]).map(n=>n.nodeType===3?n.textContent:n.nodeType===1&&!n.matches('input,select,textarea,button')?labelText(n):'').join(' ').trim();
  let indexed=new Map();
  const snapshot=(options={})=>{
    geometryRequired=options.geometryRequired!==false;
    hiddenCache=new WeakMap();
    documentHidden=new WeakMap();
    indexed=new Map();
    const elements=[],tables=[],frames=[],texts=[],secrets=[];
    let totalElements=0,tablesTruncated=false,frameLimit=false;
    const visit=(doc,prefix,depth)=>{
      texts.push(text(doc.body));
      for(const e of Array.from(doc.querySelectorAll('input')).filter(secret))if(e.value)secrets.push(String(e.value));
      const all=Array.from(doc.querySelectorAll(selector)).filter(visible);
      totalElements+=all.length;
      const selected=all.map((e,i)=>({e,i}));
      if(all.length>500-elements.length){
        // Keep the bounded snapshot useful when portals append menus after
        // long result lists. IDs stay tied to actual document positions.
        // Secret fields remain observable (redacted) for authentication guards.
        const priority=e=>secret(e)?0:actions(e).some(a=>a!=='scroll')?1:2;
        selected.sort((a,b)=>priority(a.e)-priority(b.e)||a.i-b.i);
      }
      for(const {e,i} of selected.slice(0,500-elements.length)){
        const id=prefix+i,r=e.getBoundingClientRect(),hidden=secret(e);
        indexed.set(id,e);
        const labels=Array.from(e.labels||[]);if(!labels.length&&e.closest('label'))labels.push(e.closest('label'));
        const labelledBy=String(e.getAttribute('aria-labelledby')||'').split(/\s+/).filter(Boolean).slice(0,16).map(key=>text(doc.getElementById(key))).join(' ').trim();
        const name=String(labelledBy||e.getAttribute('aria-label')||labels.map(labelText).join(' ')||e.getAttribute('alt')||(e.matches('input[type=submit],input[type=button],input[type=reset]')?e.value:'')||text(e)||e.getAttribute('title')||'').replace(/\s+/gu,' ').trim();
        const value='value' in e?String(e.value):null;
        const row={id,frame:prefix||null,role:e.getAttribute('role')||({checkbox:'checkbox',radio:'radio',button:'button',submit:'button',image:'button',reset:'button'}[e.type])||({INPUT:'textbox',TEXTAREA:'textbox',BUTTON:'button',A:'link',SELECT:'combobox',TABLE:'table',IMG:'image'}[e.tagName]||e.tagName.toLowerCase()),
          name,nameTruncated:name.length>2000,value:hidden?'[redacted]':value,valueTruncated:!hidden&&value!==null&&value.length>10000,secret:hidden,enabled:!disabled(e),checked:'checked' in e?e.checked:null,
          actions:actions(e),geometryAvailable:r.width>0&&r.height>0,bounds:{x:r.x,y:r.y,w:r.width,h:r.height}};
        if(e.matches('a[href]')){row.href=String(e.href||e.getAttribute('href')||'');row.hrefTruncated=row.href.length>4000;}
        // Keep dates attached to their own article/result. A flat page text
        // cannot safely associate one card's age with a neighboring headline.
        if(e.matches('a[href],h1,h2,h3')){
          const container=e.closest('article,[itemtype*="Article"],li')||e.parentElement;
          const dates=Array.from(container?.querySelectorAll('time')||[]).slice(0,8);
          if(dates.length)row.dates=dates.map(d=>({text:text(d).slice(0,200),datetime:String(d.getAttribute('datetime')||'').slice(0,100)}));
        }
        if(e.hasAttribute('aria-expanded'))row.expanded=e.getAttribute('aria-expanded')==='true';
        if(e.hasAttribute('aria-selected'))row.selected=e.getAttribute('aria-selected')==='true';
        if(e.matches('input,textarea,select,button')){
          row.type=String(e.type||e.tagName.toLowerCase()).slice(0,100);
          row.placeholder=String(e.getAttribute('placeholder')||'').slice(0,1000);
          row.inputName=String(e.getAttribute('name')||'').slice(0,500);
          row.readOnly=readOnly(e);
          if(editable(e)&&actions(e).includes('submit'))row.submission=e.form?'form':'enter';
          // Native .form also covers controls associated through a form= ID.
          // These are observed semantics; actions never synthesize search URLs.
          if(e.form){const f=e.form;row.form={method:String(f.method||'get').slice(0,20),action:String(f.action||doc.location.href),role:String(f.getAttribute('role')||'').slice(0,100),name:String(f.getAttribute('aria-label')||f.getAttribute('name')||'').slice(0,500)};row.form.actionTruncated=row.form.action.length>4000;}
        }
        if(e.matches('select')){
          const options=Array.from(e.options||e.querySelectorAll('option'));
          row.options=options.slice(0,200).map(o=>({value:String(o.value||''),label:String(o.label||text(o)).replace(/\s+/gu,' ').trim(),selected:!!o.selected,enabled:!o.disabled&&!o.hasAttribute('disabled')&&!o.closest('optgroup[disabled]')}));
          row.optionsTruncated=options.length>200||row.options.some(o=>o.value.length>2000||o.label.length>1000);
        }
        elements.push(row);
      }
      for(const t of Array.from(doc.querySelectorAll('table')).filter(visible)){
        if(tables.length>=20){tablesTruncated=true;break;}
        // Obscura does not always implement HTMLTableElement.rows/cells.
        const rows=Array.from(t.rows||t.querySelectorAll('tr')).filter(r=>r.closest('table')===t);
        if(rows.length>100)tablesTruncated=true;
        tables.push(rows.slice(0,100).map(r=>{
          const cells=Array.from(r.cells||r.querySelectorAll('th,td'));
          if(cells.length>100)tablesTruncated=true;
          return cells.slice(0,100).map(c=>{const s=text(c);if(s.length>4000)tablesTruncated=true;return s;});
        }));
      }
      const children=Array.from(doc.querySelectorAll('iframe,frame')).filter(visible);
      for(let i=0;i<children.length;i++){
        if(frames.length>=30||depth>=4){frameLimit=true;break;}
        const e=children[i],id=prefix+'f'+i+'.';
        try{
          const child=e.contentDocument;
          if(!child?.body)throw Error('Unavailable or cross-origin frame');
          // Only same-origin frames inherit this tab's observation/action grant.
          const url=child.location.href;
          if(url!=='about:blank'&&child.location.origin!==location.origin)throw Error('Frame origin needs an owner grant');
          frames.push({id,url,status:'observed',title:child.title});visit(child,id,depth+1);
        }catch(_){frames.push({id,url:e.getAttribute('src')||'',status:'origin_or_loading_boundary',actions:[]});}
      }
    };
    visit(document,'',0);
    const mask=s=>secrets.sort((a,b)=>b.length-a.length).reduce((v,p)=>v.split(p).join('[redacted]'),String(s??''));
    const rawText=texts.join('\n'),body=mask(rawText);
    for(const e of elements){
      e.name=mask(e.name).slice(0,2000);if(e.value!==null)e.value=mask(e.value).slice(0,10000);
      if(e.href!==undefined)e.href=mask(e.href).slice(0,4000);
      for(const field of ['placeholder','inputName'])if(e[field]!==undefined)e[field]=mask(e[field]);
      if(e.form){e.form.action=mask(e.form.action).slice(0,4000);e.form.name=mask(e.form.name);}
      if(e.dates)for(const d of e.dates){d.text=mask(d.text);d.datetime=mask(d.datetime);}
      if(e.options)for(const o of e.options){o.value=mask(o.value).slice(0,2000);o.label=mask(o.label).slice(0,1000);}
    }
    for(const table of tables)for(const row of table)for(let i=0;i<row.length;i++)row[i]=mask(row[i]).slice(0,4000);
    const login=Array.from(indexed.values()).some(e=>e.type==='password'&&e.closest('form')&&/sign in|log in|login|authenticate/i.test(text(e.closest('form'))));
    const value={title:mask(document.title),url:location.href,text:body.slice(0,40000),elements,totalElements,truncated:totalElements>500||body.length>40000||frameLimit,tables,tablesTruncated,frames,readyState:document.readyState,
      authentication:{required:login,needs:login?'Paul':null},automation:{userAgent:navigator.userAgent,webdriver:navigator.webdriver},
      frontier:['Cross-origin frames need a separate owner grant; canvas pixels and closed shadow roots need visual observation.']};
    value.accessibility=elements.map(e=>`${e.id} ${e.role} ${e.name}${e.value===null?'':' value='+e.value}`).join('\n');
    // Animated transforms and layout reflow do not invalidate a semantic DOM
    // action. Values, names, IDs, URLs, enabled state and content still do.
    const raw=JSON.stringify(value,(key,v)=>['bounds','geometryAvailable'].includes(key)?undefined:v);let hash=2166136261;for(let i=0;i<raw.length;i++)hash=Math.imul(hash^raw.charCodeAt(i),16777619);
    value.revision=(hash>>>0).toString(16);return value;
  };
  const get=(value,path)=>{
    if(typeof path!=='string'||!path.startsWith('/')||path.length>1000)throw Error('Verification needs a bounded JSON Pointer');
    for(const raw of path.slice(1).split('/')){const key=raw.replace(/~1/g,'/').replace(/~0/g,'~');if(['__proto__','prototype','constructor'].includes(key))throw Error('Invalid verification pointer');value=value?.[key];}
    return value;
  };
  const verify=(before,after,args)=>{
    if(args.expect){
      const expected=args.expect,actual=get(after,expected.path);
      if(Object.keys(expected).some(k=>!['path','equals','contains'].includes(k))||('equals' in expected)===('contains' in expected))throw Error('Verification needs exactly equals or contains');
      return {verified:'equals' in expected?JSON.stringify(actual)===JSON.stringify(expected.equals):typeof actual==='string'&&actual.includes(String(expected.contains)),check:expected,actual};
    }
    const row=after.elements.find(e=>e.id===String(args.element));
    if(args.action==='fill'||args.action==='select')return {verified:!!row&&row.value===String(args.value??''),check:{element:args.element,value:String(args.value??'')}};
    if(args.action==='scroll'){const e=indexed.get(String(args.element)),r=e?.getBoundingClientRect();return {verified:!!r&&r.top>=0&&r.top<e.ownerDocument.defaultView.innerHeight,check:'target_in_view'};}
    return {verified:before.revision!==after.revision,check:'observed_state_changed'};
  };
  const act=args=>{
    const e=indexed.get(String(args.element));
    if(!e||!actions(e).includes(args.action))throw Error('Target unavailable');
    if(args.action==='click'){
      const win=e.ownerDocument.defaultView,r=e.getBoundingClientRect();
      const init={bubbles:true,cancelable:true,composed:true,view:win,button:0,clientX:r.x+r.width/2,clientY:r.y+r.height/2};
      // Menus commonly activate on pointerdown, while links/forms activate on
      // click. Send one press/release sequence and exactly one click; never
      // retry a dispatch because its effect was not confirmed.
      if(typeof win.PointerEvent==='function')e.dispatchEvent(new win.PointerEvent('pointerdown',{...init,buttons:1,pointerId:1,pointerType:'mouse',isPrimary:true}));
      e.dispatchEvent(new win.MouseEvent('mousedown',{...init,buttons:1}));
      if(typeof win.PointerEvent==='function')e.dispatchEvent(new win.PointerEvent('pointerup',{...init,buttons:0,pointerId:1,pointerType:'mouse',isPrimary:true}));
      e.dispatchEvent(new win.MouseEvent('mouseup',{...init,buttons:0}));
      e.click();
    }
    else if(args.action==='fill'){
      const win=e.ownerDocument.defaultView,proto=e.tagName==='TEXTAREA'?win.HTMLTextAreaElement.prototype:win.HTMLInputElement.prototype;
      // WebView2 exposes a native prototype setter; semantic DOM engines may
      // put value on the instance instead. Both paths still require a fresh
      // observed value match in verify(), so assignment alone is no receipt.
      const setter=Object.getOwnPropertyDescriptor(proto,'value')?.set;
      if(setter)setter.call(e,String(args.value??''));
      else e.value=String(args.value??'');
      e.dispatchEvent(new win.Event('input',{bubbles:true}));e.dispatchEvent(new win.Event('change',{bubbles:true}));
    }else if(args.action==='select'){e.value=String(args.value??'');e.dispatchEvent(new e.ownerDocument.defaultView.Event('change',{bubbles:true}));}
    else if(args.action==='submit'){
      const form=e.form,win=e.ownerDocument.defaultView;
      if(!form){
        if(!searchEditable(e)||readOnly(e))throw Error('Observed input has no submission affordance');
        // Search widgets often submit through their Enter handler rather than
        // an HTML form. Dispatch one keyboard sequence to the observed field;
        // handlers own navigation, and the executor still checks the effect.
        const init={key:'Enter',code:'Enter',keyCode:13,which:13,charCode:13,bubbles:true,cancelable:true,composed:true};
        const allowed=e.dispatchEvent(new win.KeyboardEvent('keydown',init));
        if(allowed)e.dispatchEvent(new win.KeyboardEvent('keypress',init));
        e.dispatchEvent(new win.KeyboardEvent('keyup',init));
      }
      else if(typeof form.requestSubmit==='function')form.requestSubmit();
      else {
        if(typeof form.checkValidity==='function'&&!form.checkValidity())return;
        const event=new win.Event('submit',{bubbles:true,cancelable:true});
        if(form.dispatchEvent(event)){
          const submit=win.HTMLFormElement?.prototype?.submit;
          if(typeof submit!=='function')throw Error('Form submission unavailable in this engine');
          submit.call(form);
        }
      }
    }
    else if(args.action==='drag'){
      const target=indexed.get(String(args.destination)),win=e.ownerDocument.defaultView;
      if(!target||target.ownerDocument!==e.ownerDocument||secret(target)||disabled(target)||!visible(target))throw Error('Drag destination unavailable');
      if(typeof win.DataTransfer!=='function'||typeof win.DragEvent!=='function')throw Error('This engine does not support drag events');
      const dataTransfer=new win.DataTransfer(),start=e.getBoundingClientRect(),end=target.getBoundingClientRect();
      const dispatch=(node,type,r)=>node.dispatchEvent(new win.DragEvent(type,{bubbles:true,cancelable:true,composed:true,dataTransfer,clientX:r.x+r.width/2,clientY:r.y+r.height/2}));
      if(dispatch(e,'dragstart',start)){
        dispatch(target,'dragenter',end);
        // HTML drop targets opt in by cancelling dragover. Never manufacture a drop.
        if(!dispatch(target,'dragover',end))dispatch(target,'drop',end);
      }
      dispatch(e,'dragend',end);
    }
    else if(args.action==='scroll')e.scrollIntoView({block:'center',behavior:'instant'});
    else throw Error('Unknown action');
  };
  Object.defineProperty(globalThis,'__neyviaProjection',{value:Object.freeze({snapshot,verify,act}),writable:false,configurable:false});
})();
