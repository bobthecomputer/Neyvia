/* Optional visual facts for the existing perception graph. No actions or network. */
(graph) => {
  const started = performance.now(), nodes = [], ids = new WeakMap();
  const textMeasure=document.createElement('canvas').getContext('2d');
  // One hidden nowrap span measures text with the layout engine itself.
  const probe=document.createElement('span');
  const layoutWidth=(t,cs)=>{probe.textContent=t;probe.style.cssText='position:absolute;left:-99999px;top:0;visibility:hidden;white-space:nowrap;font:'+
    (cs.font||[cs.fontStyle,cs.fontWeight,cs.fontSize,cs.fontFamily].join(' '))+';letter-spacing:'+cs.letterSpacing;
    if(!probe.isConnected)document.body.appendChild(probe);return probe.getBoundingClientRect().width;};
  const all = Array.from(document.querySelectorAll('*')).filter(e => {
    const s = getComputedStyle(e), r = e.getBoundingClientRect();
    return !['SCRIPT','STYLE','NOSCRIPT','HEAD','META','LINK'].includes(e.tagName) &&
      s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0 && r.right>0 && r.bottom>0 && r.left<innerWidth && r.top<innerHeight;
  });
  const rect = r => ({x:r.x,y:r.y,w:r.width,h:r.height});
  const rgba = value => {
    const m = value.match(/^rgba?\(([^)]+)\)$/);
    if (!m) return null;
    const a = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    return a.length >= 3 && a.every(Number.isFinite) ? [...a.slice(0,3),a[3] ?? 1] : null;
  };
  const lum = c => c.slice(0,3).map(v => v/255).map(v => v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((v,n,i)=>v+n*[.2126,.7152,.0722][i],0);
  Array.from(document.querySelectorAll('*')).forEach((e,i)=>ids.set(e,'v'+i));
  const chosen = all.filter(e => e.matches('button,input,textarea,select,a,canvas,img,[role],[class*="panel"],[class*="peek"],[class*="floating"]') ||
    Array.from(e.childNodes).some(n=>n.nodeType===3 && n.textContent.trim())).slice(0,700);
  const secrets = Array.from(document.querySelectorAll('input')).filter(e=>e.type==='password'||/password|cc-number|cc-csc|one-time-code/.test(e.autocomplete||'')).map(e=>e.value).filter(Boolean);
  const mask = t => secrets.reduce((s,p)=>s.split(p).join('[redacted]'),t);
  for (const e of chosen) {
    const s=getComputedStyle(e), r=e.getBoundingClientRect();
    const isSecret=e.type==='password'||/password|cc-number|cc-csc|one-time-code/.test(e.autocomplete||'');
    const direct=Array.from(e.childNodes).filter(n=>n.nodeType===3).map(n=>n.textContent).join(' ').trim();
    const text=mask(isSecret?'[redacted]':String(direct || (e.matches('input,textarea')?e.value || e.placeholder:'')).slice(0,1000));
    let clip={left:-Infinity,top:-Infinity,right:Infinity,bottom:Infinity}, clipped=false, firstGlyphOutside=false;
    // Clips stop at the nearest scroll container: content scrolled out of a
    // scrollable area is reachable, not clipped. Record it separately.
    let scrolledOut=false;
    for(let p=e.parentElement===null?null:e;p;p=p.parentElement) {
      const ps=getComputedStyle(p),pr=p.getBoundingClientRect();
      if(p!==e&&(/auto|scroll/.test(ps.overflowY)&&p.scrollHeight>p.clientHeight+1||/auto|scroll/.test(ps.overflowX)&&p.scrollWidth>p.clientWidth+1)){
        scrolledOut=r.bottom>pr.bottom+1||r.top<pr.top-1||r.right>pr.right+1||r.left<pr.left-1;break;}
      if(/hidden|clip/.test(ps.overflowX)){clip.left=Math.max(clip.left,pr.left);clip.right=Math.min(clip.right,pr.right);}
      if(/hidden|clip/.test(ps.overflowY)){clip.top=Math.max(clip.top,pr.top);clip.bottom=Math.min(clip.bottom,pr.bottom);}
    }
    for(const t of Array.from(e.childNodes).filter(n=>n.nodeType===3&&n.textContent.trim())) {
      const range=document.createRange();range.selectNodeContents(t);
      // Line boxes include leading: vertical clipping counts only when more
      // than a third of the font size is cut.
      const px=parseFloat(s.fontSize)||12;
      for(const b of range.getClientRects()){const slack=Math.max(1,(b.height-px)/2+px*0.34);
        if(b.left<clip.left-1||b.right>clip.right+1||b.top<clip.top-slack||b.bottom>clip.bottom+slack)clipped=true;}
      const first=t.textContent.search(/\S/);range.setStart(t,first);range.setEnd(t,first+1);
      const g=range.getBoundingClientRect();if(g.left<clip.left-1||g.right>clip.right+1)firstGlyphOutside=true;
    }
    textMeasure.font=s.font || [s.fontWeight,s.fontSize,s.fontFamily].join(' ');
    const measured=text ? textMeasure.measureText(text).width : 0;
    // Embedded engines can expose stub canvas metrics. Never turn them into evidence.
    const fontPixels=parseFloat(s.fontSize), probeWidth=textMeasure.measureText('M').width;
    const textMetricsReliable=Number.isFinite(fontPixels)&&probeWidth>fontPixels*.1&&probeWidth<fontPixels*2;
    // Fallback: the layout engine's own width for the same text in a hidden
    // nowrap span (works where canvas metrics are stubs).
    let laidOut=null;
    const clipsX=/hidden|clip/.test(s.overflowX)&&!/^inline$/.test(s.display)&&e.clientWidth>0;
    if(text&&!textMetricsReliable&&clipsX&&s.whiteSpace==='nowrap'){
      laidOut=layoutWidth(text,s);
      if(!(laidOut>0))laidOut=null;
    }
    const naturalTextWidth=textMetricsReliable ? measured : laidOut;
    // A single word wider than its clipping content box cannot wrap: it is cut.
    if(text&&clipsX){
      const word=text.split(/\s+/).reduce((a,b)=>b.length>a.length?b:a,'');
      const wordWidth=layoutWidth(word,s);
      const box=e.clientWidth-(parseFloat(s.paddingLeft)||0)-(parseFloat(s.paddingRight)||0);
      if(wordWidth>box+1&&!(s.textOverflow==='ellipsis'&&s.whiteSpace==='nowrap'))clipped=true;
    }
    // Inline boxes report clientWidth 0 and ignore overflow; only block-level clips count.
    // End truncation with text-overflow:ellipsis is the intended, readable form
    // ("GPT-5…"); only an unmarked cut counts here.
    if(text && /hidden|clip/.test(s.overflowX) && s.whiteSpace==='nowrap' && s.textOverflow!=='ellipsis' && !/^inline$/.test(s.display) && e.clientWidth>0 && naturalTextWidth!==null && naturalTextWidth>e.clientWidth+1)clipped=true;
    const bg=rgba(s.backgroundColor), fg=rgba(s.color);
    let effective=[255,255,255,1], chain=[], uncertain=false,opacity=1;
    for(let p=e;p;p=p.parentElement){const ps=getComputedStyle(p);opacity*=Number(ps.opacity);chain.unshift(ps);if(!/^(none|initial|)$/.test(ps.backgroundImage||'')||!/^(none|initial|)$/.test(ps.filter||''))uncertain=true;}
    for(const ps of chain){const c=rgba(ps.backgroundColor);if(c)effective=c.slice(0,3).map((v,i)=>v*c[3]+effective[i]*(1-c[3])).concat(1);else uncertain=true;}
    let contrast=null;
    // Transparent text (e.g. a PDF text layer over its canvas) is not painted.
    const transparentText=!!fg&&fg[3]<0.05;
    if(fg&&!transparentText&&!uncertain&&opacity===1){const painted=fg.slice(0,3).map((v,i)=>v*fg[3]+effective[i]*(1-fg[3]));const a=lum(painted),b=lum(effective);contrast=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);}
    const control=e.matches('button,input,select,textarea,a[href],[role=button],[role=tab]');
    const surface=e.matches('[role=dialog],[role=menu],[class*="peek"],[class*="floating"]');
    // Document, terminal and editor text is the user's content, not UI copy.
    const userContent=!!e.closest('.textLayer,.xterm,[contenteditable="true"],pre,code')||
      (e.matches('input,textarea')&&!!e.value);
    const placeholder=e.matches('input,textarea')&&!e.value&&!!e.placeholder;
    const facts={userContent,scrolledOut,placeholder,transparentText,fontSize:parseFloat(s.fontSize)||null,textAlign:s.textAlign,
      paddingLeft:parseFloat(s.paddingLeft)||0,paddingRight:parseFloat(s.paddingRight)||0,opacity,backgroundAlpha:bg?.[3]??null,zOrder:s.zIndex,overflowX:s.overflowX,overflowY:s.overflowY,
      naturalTextWidth,textOverflow:s.textOverflow,scrollWidth:e.scrollWidth,clientWidth:e.clientWidth,clippedText:!!text&&clipped,firstGlyphOutside,
      contrastRatio:contrast,offScreenControl:control&&(r.left<0||r.right>innerWidth||s.position==='fixed'&&(r.top<0||r.bottom>innerHeight)),
      surface,behindText:[],expectedContent:false,uniform:null,overlap:[]};
    if(surface&&bg&&bg[3]<1) {
      const stack=document.elementsFromPoint(Math.max(0,Math.min(innerWidth-1,r.x+r.width/2)),Math.max(0,Math.min(innerHeight-1,r.y+r.height/2)));
      const at=stack.indexOf(e);
      if(at>=0)facts.behindText=stack.slice(at+1).filter(p=>!p.contains(e)&&!e.contains(p)&&p.innerText?.trim()).slice(0,4).map(p=>ids.get(p)).filter(Boolean);
      // Engines without a paint-order hit test: any text outside this surface's
      // subtree that intersects it is visible through the translucent body.
      if(!facts.behindText.length) facts.behindText=chosen.filter(p=>p!==e&&!p.contains(e)&&!e.contains(p)&&
        Array.from(p.childNodes).some(n=>n.nodeType===3&&n.textContent.trim())&&(()=>{const q=p.getBoundingClientRect();
        return Math.min(q.right,r.right)-Math.max(q.left,r.left)>2&&Math.min(q.bottom,r.bottom)-Math.max(q.top,r.top)>2;})()).slice(0,4).map(p=>ids.get(p));
    }
    if(e.tagName==='CANVAS'||e.tagName==='IMG') {
      facts.expectedContent=e.hasAttribute('data-content-expected')||!!e.closest('[class*="pdf"],[data-pdf-page]');
      if(facts.expectedContent)try{
        const c=document.createElement('canvas');c.width=128;c.height=128;const cx=c.getContext('2d',{willReadFrequently:true});cx.drawImage(e,0,0,128,128);
        const d=cx.getImageData(0,0,128,128).data;let lo=255,hi=0;
        for(let i=0;i<d.length;i+=4){const v=(d[i]+d[i+1]+d[i+2])/3;lo=Math.min(lo,v);hi=Math.max(hi,v);}facts.uniform=hi-lo<=4;
      }catch(_){facts.uniform=null;}
    }
    nodes.push({id:ids.get(e),parent:ids.get(e.parentElement)||null,role:e.getAttribute('role')||e.tagName.toLowerCase(),text,bounds:rect(r),facts,certainty:'observed'});
  }
  probe.remove();
  const intersect=(a,b)=>Math.min(a.x+a.w,b.x+b.w)>Math.max(a.x,b.x)+1&&Math.min(a.y+a.h,b.y+b.h)>Math.max(a.y,b.y)+1;
  for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){
    const a=nodes[i],b=nodes[j];if(a.parent&&a.parent===b.parent&&a.text&&b.text&&intersect(a.bounds,b.bounds)){a.facts.overlap.push(b.id);b.facts.overlap.push(a.id);}
  }
  return {schema:'neyvia.scene.v1',layer:'browser',surface:document.title||location.pathname,viewport:{width:innerWidth,height:innerHeight},
    nodes,truncated:chosen.length===700,transcriptionMs:performance.now()-started,sourceRevision:graph?.revision||null,
    unknown:['Closed shadow roots and cross-origin frames','Occluded or alpha-composited text contrast','Semantic expectation for unmarked blank media']};
}
