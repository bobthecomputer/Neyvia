(() => {
  if (window !== window.top || location.protocol==='about:') return;
  const core=globalThis.__neyviaProjection;
  const emit=event=>window.__TAURI_INTERNALS__.invoke('browser_page_event',{event}).catch(()=>{});
  const visible = e => { const r=e.getBoundingClientRect(), s=getComputedStyle(e); return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; };
  const secret = e => e.type==='password' || e.type==='hidden' || /password|cc-number|cc-csc|one-time-code/.test(e.autocomplete||'') || /password|secret|token|api.?key/i.test(e.name||'');
  let paused=true,grantEpoch=0;
  const grant=request=>{grantEpoch=request.epoch;paused=!request.enabled;};
  const snapshot=()=>{
    const value=core.snapshot(), records={};
    try {for(let i=0;i<localStorage.length;i++){
      const key=localStorage.key(i);
      if(/^neyvia\.app-factory\.[A-Za-z0-9._-]+\.(items\.v1|capability-runs\.v2)$/.test(key)){
        const raw=localStorage.getItem(key);
        if(raw.length<=512000&&Array.isArray(JSON.parse(raw)))records[key]=raw;
      }
    }}catch{}
    return {...value,localAppStorage:records};
  };
  const observe=actionId=>emit({type:'projection',actionId,projection:snapshot()});
  const perform=async request=>{
    const before=snapshot(),row=before.elements.find(e=>e.id===String(request.element));
    const finish=result=>emit({type:'action',actionId:request.id,ok:result.ok,result});
    if(paused||request.grantEpoch!==grantEpoch)return finish({ok:false,status:'paused_by_user',dispatched:false});
    if(before.authentication.required)return finish({ok:false,status:'auth_required',needs:'Paul',dispatched:false});
    if(before.revision!==request.revision)return finish({ok:false,status:'stale_projection',revision:before.revision,dispatched:false});
    if(!row||row.secret||!row.enabled||!row.actions.includes(request.action))return finish({ok:false,status:'action_unavailable',dispatched:false});
    try{
      core.verify(before,before,request);
      core.act(request);
      const deadline=performance.now()+2000;
      let after,verification;
      do{
        await new Promise(resolve=>setTimeout(resolve,20));
        after=snapshot();verification=core.verify(before,after,request);
        if(verification.verified)break;
      }while(performance.now()<deadline);
      verification.beforeRevision=before.revision;verification.afterRevision=after.revision;
      await emit({type:'projection',projection:after});
      return finish({ok:verification.verified,status:verification.verified?'verified':'effect_unconfirmed',action:request.action,element:String(request.element),verification,observation:after});
    }catch(error){return finish({ok:false,status:'page_action_failed',message:String(error)});}
  };
  const reader = actionId => {
    // Read the same live document and revision as observe; never serialize or execute article HTML.
    const projection=snapshot();
    if(document.readyState!=='complete' || !document.body) {
      emit({type:'action',actionId,ok:false,error:'This page is still loading. Wait for it to finish, then try Reader again.'});return;
    }
    const readable=e=>visible(e)&&!e.closest('[hidden],[aria-hidden="true"],[data-private],[data-secret],[contenteditable]');
    const source=[...document.querySelectorAll('article')].find(readable)||[...document.querySelectorAll('main,[role=main]')].find(readable)||document.body;
    if(!readable(source)) {
      emit({type:'action',actionId,ok:false,error:'Reader cannot extract a private, hidden or editable page root. Show the page or open a readable article, then try again.'});return;
    }
    const clone=source.cloneNode(true), originals=[source,...source.querySelectorAll('*')], copies=[clone,...clone.querySelectorAll('*')];
    originals.forEach((e,i)=>{if(e!==source && (!visible(e)||e.matches('script,style,noscript,nav,aside,footer,form,input,textarea,select,button,iframe,object,embed,[hidden],[aria-hidden="true"],[contenteditable],[data-private],[data-secret]')))copies[i].remove();});
    const secrets=[...document.querySelectorAll('input,textarea')].filter(secret).map(e=>e.value).filter(Boolean).sort((a,b)=>b.length-a.length);
    const clean=s=>secrets.reduce((v,p)=>v.split(p).join('[redacted]'),String(s||'')).replace(/\s+/g,' ').trim();
    const blocks=[];let remaining=40000,truncated=false;
    const add=(type,raw)=>{const text=clean(raw);if(!text)return;if(blocks.length>=200||remaining<=0){truncated=true;return;}const bounded=text.slice(0,Math.min(4000,remaining));if(bounded.length<text.length)truncated=true;blocks.push({type,text:bounded});remaining-=bounded.length;};
    const candidates=[...clone.querySelectorAll('h1,h2,h3,p,li,blockquote,pre')];
    for(const e of candidates){if(e.querySelector('h1,h2,h3,p,li,blockquote,pre'))continue;add(/^H[1-3]$/.test(e.tagName)?'h':'p',e.textContent);}
    if(!blocks.length)add('p',clone.textContent);
    const title=clean(clone.querySelector('h1')?.textContent||document.title).slice(0,1000);
    const text=blocks.map(b=>b.text).join('\n');
    if(!text){emit({type:'action',actionId,ok:false,error:'This page has no readable article text. Show the page or open an article, then try Reader again.'});return;}
    emit({type:'reader',actionId,projection,reader:{revision:projection.revision,title,url:projection.url,blocks,paragraphs:blocks.filter(b=>b.type==='p').map(b=>b.text),text,truncated}});
  };
  const verifyNavigation=async request=>{
    const after=snapshot();
    const verification=core.verify({revision:request.revision},after,request);
    verification.beforeRevision=request.revision;verification.afterRevision=after.revision;
    await emit({type:'projection',projection:after});
    return emit({type:'action',actionId:request.id,ok:verification.verified,result:{ok:verification.verified,status:verification.verified?'verified':'effect_unconfirmed',verification,observation:after}});
  };
  const dom = request => {
    const current=snapshot();
    const values=[...document.querySelectorAll(request.selector)].slice(0,request.limit);
    const passwords=[...document.querySelectorAll('input')].filter(secret).map(e=>e.value).filter(Boolean);
    const mask=s=>passwords.reduce((v,p)=>v.split(p).join('[redacted]'),String(s||''));
    return {ok:true,revision:current.revision,url:location.href,elements:values.map(e=>({visible:visible(e),innerText:secret(e)?'[redacted]':mask(e.innerText).slice(0,40000),attributes:Object.fromEntries(request.attributes.map(a=>[a,secret(e)?'[redacted]':mask(e.getAttribute(a))]))}))};
  };
  const annotate = request => {
    const current=snapshot();
    if(paused || request.grantEpoch!==grantEpoch)return {ok:false,status:'paused_by_user'};
    if(current.revision!==request.revision)return {ok:false,status:'stale_projection'};
    const r=request.rectangle;
    if(!r || !['x','y','width','height'].every(k=>Number.isFinite(r[k]) && r[k]>=0 && r[k]<=100) || r.width<=0 || r.height<=0 || r.x+r.width>100 || r.y+r.height>100 || typeof request.comment!=='string' || request.comment.length>4000)return {ok:false,status:'invalid_annotation'};
    const overlay=document.createElement('div');
    overlay.setAttribute('data-neyvia-annotation-proof','true');
    Object.assign(overlay.style,{position:'fixed',zIndex:'2147483647',pointerEvents:'none',left:`${r.x}%`,top:`${r.y}%`,width:`${r.width}%`,height:`${r.height}%`,border:'3px solid #f2b84b',borderRadius:'8px',boxShadow:'0 0 0 9999px rgba(7,16,31,.34)',boxSizing:'border-box'});
    const label=document.createElement('span');label.textContent=request.comment.slice(0,120);
    Object.assign(label.style,{position:'absolute',left:'0',bottom:'100%',background:'#07101f',color:'#fff',padding:'6px 9px',font:'600 12px/1.35 system-ui'});
    overlay.appendChild(label);document.documentElement.appendChild(overlay);
    return {ok:true,rectangle:r,comment:request.comment};
  };
  Object.defineProperty(window,'__neyviaBrowser',{value:Object.freeze({observe,reader,perform,grant,verifyNavigation,snapshot,dom,annotate}),writable:false,configurable:false});
  let timer;
  const changed=()=>{clearTimeout(timer);timer=setTimeout(()=>observe(),60);};
  const ready=()=>{
    observe();
    const watch=doc=>{new MutationObserver(changed).observe(doc.documentElement,{subtree:true,childList:true,attributes:true,characterData:true});doc.addEventListener('input',changed,true);doc.addEventListener('change',changed,true);
      for(const frame of Array.from(doc.querySelectorAll('iframe'))){frame.addEventListener('load',()=>{try{if(frame.contentDocument)watch(frame.contentDocument);}catch(_){}changed();});try{if(frame.contentDocument?.documentElement)watch(frame.contentDocument);}catch(_){}}
      for(const type of ['pointerdown','keydown','wheel'])doc.addEventListener(type,e=>{if(e.isTrusted){paused=true;emit({type:'user_input'});}},true);
    };watch(document);
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ready,{once:true});else ready();
})();
