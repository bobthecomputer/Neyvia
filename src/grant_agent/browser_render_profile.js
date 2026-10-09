/** Explicit Obscura render compatibility. Never reports unsupported native APIs as native. */
(profile => {
  const nativeMatchMedia = window.matchMedia.bind(window);
  const preference = query => query.replace(/\(prefers-color-scheme\s*:\s*(dark|light)\)/gi,
    (rule, value) => profile.nativeColorScheme ? rule : (profile.theme === value.toLowerCase() ? '(min-width:0px)' : '(max-width:-1px)'))
    .replace(/\(prefers-reduced-motion\s*:\s*(reduce|no-preference)\)/gi,
    (_, value) => (profile.reducedMotion ? 'reduce' : 'no-preference') === value.toLowerCase() ? '(min-width:0px)' : '(max-width:-1px)');
  window.matchMedia = query => nativeMatchMedia(preference(String(query)));
  const transformed = new WeakSet();
  const styleTexts = new WeakMap();
  // Root SVG viewport coordinates, including preserveAspectRatio letterboxing.
  // Native APIs win; nested/transformed SVGs abstain rather than invent geometry.
  const matrix = (a,b,c,d,e,f) => ({a,b,c,d,e,f,inverse(){
    const det=a*d-b*c;if(!Number.isFinite(det)||Math.abs(det)<1e-12)throw new Error('Singular SVG matrix');
    return matrix(d/det,-b/det,-c/det,a/det,(c*f-d*e)/det,(b*e-a*f)/det);
  }});
  const svgPoint = (x=0,y=0) => ({x,y,matrixTransform(m){return svgPoint(m.a*this.x+m.c*this.y+m.e,m.b*this.x+m.d*this.y+m.f);}});
  function svgCoordinates() {
    for(const svg of [...document.querySelectorAll('svg')]) {
      if(typeof svg.createSVGPoint!=='function')svg.createSVGPoint=()=>svgPoint();
      if(typeof svg.getScreenCTM==='function')continue;
      svg.getScreenCTM=()=>{
        if(svg.parentElement?.closest('svg'))return null;
        for(let node=svg;node;node=node.parentElement){
          const transform=getComputedStyle(node).transform;
          if(node.hasAttribute('transform')||transform&&transform!=='none')return null;
        }
        const r=svg.getBoundingClientRect();if(!r.width||!r.height)return null;
        const raw=svg.getAttribute('viewBox');
        const box=raw?raw.trim().split(/[\s,]+/).map(Number):[0,0,r.width,r.height];
        if(box.length!==4||box.some(v=>!Number.isFinite(v))||box[2]<=0||box[3]<=0)return null;
        const [x,y,w,h]=box,par=(svg.getAttribute('preserveAspectRatio')||'xMidYMid meet').replace(/^defer\s+/,'').trim();
        let sx=r.width/w,sy=r.height/h,dx=0,dy=0;
        if(par!=='none'){
          const match=/^(x(?:Min|Mid|Max)Y(?:Min|Mid|Max))(?:\s+(meet|slice))?$/.exec(par);if(!match)return null;
          sx=sy=match[2]==='slice'?Math.max(sx,sy):Math.min(sx,sy);
          dx=(r.width-w*sx)*(match[1].startsWith('xMin')?0:match[1].startsWith('xMax')?1:.5);
          dy=(r.height-h*sy)*(match[1].endsWith('YMin')?0:match[1].endsWith('YMax')?1:.5);
        }
        return matrix(sx,0,0,sy,r.left+dx-x*sx,r.top+dy-y*sy);
      };
    }
  }
  // Obscura paints SVG primitives but omits their layout boxes and input hits.
  // Bridge a bounded geometric subset to real HTML hit regions; page handlers
  // still receive the original SVG node. Unsupported visible controls abstain.
  const svgHits=new Map(),hitOwners=new WeakMap(),nativeHit=document.elementFromPoint.bind(document);
  const combine=(a,b)=>matrix(a.a*b.a,0,0,a.d*b.d,a.a*b.e+a.e,a.d*b.f+a.f);
  function primitiveGeometry(node,root) {
    let m=root.getScreenCTM?.();if(!m||m.b||m.c)return null;
    const chain=[];for(let n=node;n&&n!==root;n=n.parentElement)chain.unshift(n);
    for(const n of chain){
      const css=getComputedStyle(n);if(css.display==='none'||css.visibility==='hidden'||css.pointerEvents==='none')return [];
      if(css.transform&&css.transform!=='none')return null;
      const text=n.getAttribute('transform')||'';let rest=text;
      for(const match of text.matchAll(/(translate|scale|matrix)\s*\(([^)]*)\)/g)){
        const values=match[2].trim().split(/[\s,]+/).map(Number);if(values.some(v=>!Number.isFinite(v)))return null;
        let t;if(match[1]==='translate'&&values.length>=1&&values.length<=2)t=matrix(1,0,0,1,values[0],values[1]||0);
        else if(match[1]==='scale'&&values.length>=1&&values.length<=2)t=matrix(values[0],0,0,values[1]??values[0],0,0);
        else if(match[1]==='matrix'&&values.length===6&&values[1]===0&&values[2]===0)t=matrix(...values);
        else return null;
        m=combine(m,t);rest=rest.replace(match[0],'');
      }
      if(rest.trim())return null;
    }
    const number=(key,fallback=0)=>{const raw=node.getAttribute(key);return raw===null?fallback:Number(raw);};
    let x,y,w,h,ellipse=false;
    if(node.matches('circle,ellipse')){const rx=number(node.matches('circle')?'r':'rx'),ry=number(node.matches('circle')?'r':'ry');x=number('cx')-rx;y=number('cy')-ry;w=rx*2;h=ry*2;ellipse=true;}
    else if(node.matches('rect')){x=number('x');y=number('y');w=number('width');h=number('height');}
    else return null;
    if([x,y,w,h,m.a,m.d].some(v=>!Number.isFinite(v))||w<=0||h<=0||!m.a||!m.d)return null;
    const left=Math.min(m.a*x+m.e,m.a*(x+w)+m.e),top=Math.min(m.d*y+m.f,m.d*(y+h)+m.f);
    return [{x:left,y:top,width:Math.abs(m.a*w),height:Math.abs(m.d*h),ellipse}];
  }
  const hitShapes=node=>{
    const root=node.closest('svg');if(!root)return null;
    const shapes=node.matches('g,a')?[...node.querySelectorAll('circle,ellipse,rect,path,polygon,polyline,line,use,image')]:[node];
    if(!shapes.length)return null;
    const result=[];for(const shape of shapes){const geometry=primitiveGeometry(shape,root);if(!geometry)return null;result.push(...geometry);}return result;
  };
  const bounds=shapes=>{if(!shapes?.length)return null;const x=Math.min(...shapes.map(s=>s.x)),y=Math.min(...shapes.map(s=>s.y)),right=Math.max(...shapes.map(s=>s.x+s.width)),bottom=Math.max(...shapes.map(s=>s.y+s.height));return {x,y,left:x,top:y,right,bottom,width:right-x,height:bottom-y,toJSON(){return {x,y,width:this.width,height:this.height};}};};
  const contains=(s,x,y)=>x>=s.x&&x<=s.x+s.width&&y>=s.y&&y<=s.y+s.height&&(!s.ellipse||((x-s.x-s.width/2)/(s.width/2))**2+((y-s.y-s.height/2)/(s.height/2))**2<=1);
  function updateSvgHits() {
    for(const [node,entry] of svgHits){
      if(!node.isConnected){entry.element.remove();svgHits.delete(node);continue;}
      const r=bounds(hitShapes(node)),root=node.closest('svg'),style=getComputedStyle(node);
      let hidden=!r||style.display==='none'||style.visibility==='hidden';
      for(let p=node.parentElement;p&&p!==root;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden')hidden=true;}
      if(hidden){entry.element.style.display='none';continue;}
      const view=root.getBoundingClientRect(),left=Math.max(r.left,view.left),top=Math.max(r.top,view.top),right=Math.min(r.right,view.right),bottom=Math.min(r.bottom,view.bottom);
      const css=`position:absolute;left:${left+scrollX}px;top:${top+scrollY}px;width:${Math.max(0,right-left)}px;height:${Math.max(0,bottom-top)}px;display:block;background:transparent;pointer-events:auto;`;
      if(entry.element.style.cssText!==css)entry.element.style.cssText=css;
    }
  }
  function svgHitRegions() {
    for(const node of [...document.querySelectorAll('svg *')]){
      const interactive=svgInteractive(node);
      if(!interactive||svgHits.has(node))continue;
      const nativeBox=node.getBoundingClientRect.bind(node),r=nativeBox();if(r.width&&r.height)continue;
      if(!bounds(hitShapes(node)))continue;
      const element=document.createElement('span');element.setAttribute('data-neyvia-svg-hit','');element.setAttribute('aria-hidden','true');
      hitOwners.set(element,node);svgHits.set(node,{element});
      node.getBoundingClientRect=()=>bounds(hitShapes(node))||nativeBox();
      node.scrollIntoView=options=>{node.closest('svg')?.scrollIntoView(options);updateSvgHits();};
      document.body.appendChild(element);
    }
    updateSvgHits();
  }
  // A root gesture may delegate pickup to a declared SVG target. Transport
  // hits through its actual supported primitive shapes, without adding a
  // second product control or pretending unsupported paths have geometry.
  const declaredGestureShape=node=>{
    if(!node.matches('rect,circle,ellipse')||getComputedStyle(node).pointerEvents==='none')return false;
    const root=node.closest('svg'),id=root?.getAttribute('data-c13-target');
    if(!id||!['drag','cross','hold'].includes(root.getAttribute('data-c13-action')))return false;
    const owner=document.getElementById(id.replace(/^#/,''));return !!owner&&(owner===node||owner.contains(node));
  };
  const svgInteractive=node=>declaredGestureShape(node)||node.matches('[tabindex],[role="button"],[role="link"],[data-c13-action],[onclick],[onpointerdown],[onmousedown],[ontouchstart]')||[...(window.__c13listeners?.get(node)||[])].some(type=>/^(click|keydown|pointerdown|mousedown|touchstart)$/.test(type));
  const ownerAt=(element,x,y)=>{const node=hitOwners.get(element);return node&&(hitShapes(node)||[]).some(s=>contains(s,x,y))?node:node?.closest('svg')||element;};
  document.elementFromPoint=(x,y)=>{updateSvgHits();return ownerAt(nativeHit(x,y),x,y);};
  window.__neyviaSvgHitGaps=()=>{
    svgCoordinates();svgHitRegions();const gaps=[];
    for(const node of [...document.querySelectorAll('svg *')]){
      if(!svgInteractive(node))continue;
      const s=getComputedStyle(node),root=node.closest('svg'),r=root.getBoundingClientRect();let hidden=s.display==='none'||s.visibility==='hidden';
      for(let p=node.parentElement;p&&p!==root;p=p.parentElement){const v=getComputedStyle(p);if(v.display==='none'||v.visibility==='hidden')hidden=true;}
      if(!hidden&&r.width&&r.height&&!bounds(hitShapes(node))&&!node.getBoundingClientRect().width)gaps.push({id:node.id,tag:node.tagName,reason:'Unsupported visible interactive SVG geometry'});
    }
    return gaps;
  };
  // Retarget real engine mouse input before the pointer compatibility transport.
  for(const type of ['mousedown','mousemove','mouseup','mouseover','mouseout','click','dblclick'])document.addEventListener(type,event=>{
    if(!hitOwners.has(event.target))return;
    const target=ownerAt(event.target,event.clientX,event.clientY);event.stopImmediatePropagation();
    const copy=new MouseEvent(type,{bubbles:true,cancelable:true,clientX:event.clientX,clientY:event.clientY,button:event.button,buttons:event.buttons,relatedTarget:hitOwners.get(event.relatedTarget)||event.relatedTarget});
    if(!target.dispatchEvent(copy))event.preventDefault();
  },true);
  document.addEventListener('scroll',updateSvgHits,true);window.addEventListener('resize',updateSvgHits);
  const nativeComputedStyle=window.getComputedStyle.bind(window),generatedAfter=new WeakMap();
  window.getComputedStyle=(node,pseudo)=>{
    if(pseudo!=='::after'||!generatedAfter.has(node))return nativeComputedStyle(node,pseudo);
    const child=generatedAfter.get(node),style=nativeComputedStyle(child);
    // The engine omits these CSSOM fields; derive fallback geometry from the
    // real materialized boxes, not the control's test annotations.
    const value=name=>name==='content'?(style.display==='none'?'none':'""'):name==='position'?'absolute':name==='right'?((node.getBoundingClientRect().right-child.getBoundingClientRect().right)+'px'):style[name];
    return new Proxy(style,{get(target,name){if(name==='getPropertyValue')return key=>value(key)??target.getPropertyValue?.(key)??'';const result=value(name);return typeof result==='function'?result.bind(target):result;}});
  };
  function generatedHitRegions() {
    // Obscura omits computed style/hit geometry for empty absolute ::after
    // regions. Materialize this bounded CSS subset as real painted children;
    // input still uses the browser's hit-test and normal event bubbling.
    const rules=[],selectors=new Set();
    const collect=items=>{for(const rule of [...items]){
      if(rule.cssRules){if(rule.type!==4||matchMedia(rule.conditionText).matches)collect(rule.cssRules);continue;}
      if(!rule.selectorText||!rule.style)continue;
      const parts=rule.selectorText.split(',').map(s=>s.trim());
      if(parts.some(s=>!s.endsWith('::after')))continue;
      let css=rule.style.cssText.replace(/content\s*:\s*none\s*(?:;|$)/gi,'content:none;display:none;');
      css=css.replace(/inset\s*:\s*([^;]+);?/gi,(_,value)=>{const v=value.trim().split(/\s+/);if(v.length>4)return 'inset:'+value+';';const top=v[0],right=v[1]||top,bottom=v[2]||top,left=v[3]||right;return `top:${top};right:${right};bottom:${bottom};left:${left};`;});
      rules.push(parts.map(s=>s.slice(0,-7)+'>[data-neyvia-after]').join(',')+'{'+css+'}');
      if(/content\s*:\s*(?:""|'')\s*(?:;|$)/i.test(rule.style.cssText)&&/position\s*:\s*absolute/i.test(rule.style.cssText))for(const s of parts)selectors.add(s.slice(0,-7));
    }};
    for(const sheet of [...document.styleSheets]){if(sheet.ownerNode?.id==='neyvia-generated-after-css')continue;try{collect(sheet.cssRules);}catch{}}
    if(!rules.length)return;
    let style=document.getElementById('neyvia-generated-after-css');
    if(!style){style=document.createElement('style');style.id='neyvia-generated-after-css';(document.head||document.documentElement).appendChild(style);}
    const css=rules.join('\n');if(style.textContent!==css)style.textContent=css;
    for(const selector of selectors){let nodes;try{nodes=document.querySelectorAll(selector);}catch{continue;}
      for(const node of [...nodes])if(!generatedAfter.has(node)){const child=document.createElement('span');child.setAttribute('data-neyvia-after','');child.setAttribute('aria-hidden','true');node.appendChild(child);generatedAfter.set(node,child);}
    }
  }
  function mediaRules(rules) {
    for (const rule of [...rules]) {
      if (rule.type === 4 && /prefers-(color-scheme|reduced-motion)/.test(rule.conditionText)) {
        rule.media.mediaText = preference(rule.conditionText);
      }
      if (rule.cssRules) mediaRules(rule.cssRules);
    }
  }
  function apply() {
    svgCoordinates();
    // The renderer paints inline links but returns empty inline hit boxes.
    // Give controls a real layout box so browser input can hit their painted text.
    for(const node of [...document.querySelectorAll('a[href],[role="button"],[data-c13-action]')]) {
      const rect=node.getBoundingClientRect(),style=getComputedStyle(node);
      if(style.display==='inline' && style.visibility!=='hidden' && (!rect.width||!rect.height))node.style.display='inline-block';
    }
    for(const style of [...document.querySelectorAll('style')]) {
      const text=style.textContent;
      if(styleTexts.get(style)===text)continue;
      const next=text.replace(/@media\s*([^{}]+)\{/gi,(_,condition)=>'@media '+preference(condition)+'{')
        .replace(/:focus(?![-\w])/g,'[data-neyvia-focused]');
      styleTexts.set(style,next);if(next!==text)style.textContent=next;
    }
    for (const sheet of [...document.styleSheets]) {
      if (transformed.has(sheet)) continue;
      try { mediaRules(sheet.cssRules); transformed.add(sheet); } catch { /* inaccessible cross-origin CSS is a declared gap */ }
    }
    generatedHitRegions();
    svgHitRegions();
  }
  const capture = new Map();
  // CDP mouse input paints/clicks but this engine omits pointer gesture events.
  // Keep the transport explicit, and abstain when a native pointer event exists.
  let mouseButtons=0, nativeMousePointerAt=0;
  document.addEventListener('pointerdown',event=>{if(event.pointerType==='mouse'&&!event.__neyviaMouseTransport)nativeMousePointerAt=Date.now();},true);
  for(const [type,pointerType] of [['mousedown','pointerdown'],['mousemove','pointermove'],['mouseup','pointerup'],['mouseover','pointerenter'],['mouseout','pointerleave']])document.addEventListener(type,event=>{
    if(type==='mousedown')mouseButtons=event.buttons||1;
    if(Date.now()-nativeMousePointerAt>=20){
      const target=capture.get(1)||event.target;
      const boundary=pointerType==='pointerenter'||pointerType==='pointerleave';
      const targets=[];
      if(boundary){for(let node=target;node&&node!==document;node=node.parentElement)if(!event.relatedTarget||!node.contains(event.relatedTarget))targets.push(node);}else targets.push(target);
      for(const node of targets){const generated=new PointerEvent(pointerType,{bubbles:!boundary,cancelable:true,clientX:event.clientX,clientY:event.clientY,relatedTarget:event.relatedTarget,pointerId:1,pointerType:'mouse',button:event.button,buttons:type==='mouseup'?0:(event.buttons||mouseButtons)});
        Object.defineProperty(generated,'__neyviaMouseTransport',{value:true});
        if(!node.dispatchEvent(generated))event.preventDefault();}
    }
    if(type==='mouseup')mouseButtons=0;
  },true);
  // Programmatic focus changes activeElement but this engine omits :focus paint.
  // Recompile that selector and track browser focus, without changing page handlers.
  let focused=null,focusEvents=0;
  const markFocus=node=>{focused?.removeAttribute('data-neyvia-focused');focused=node;node?.setAttribute('data-neyvia-focused','');};
  window.__neyviaFocus=node=>{const active=document.activeElement===node,count=focusEvents;node.focus();markFocus(node);if(!active&&focusEvents===count){node.dispatchEvent(new FocusEvent('focus',{bubbles:false}));node.dispatchEvent(new FocusEvent('focusin',{bubbles:true}));}};
  document.addEventListener('focus',event=>{focusEvents++;markFocus(event.target);},true);
  document.addEventListener('blur',event=>{if(focused===event.target)markFocus(null);},true);
  // Obscura exposes keyboard/touch events but omits HTML activation defaults.
  // Implement defaults in the browser profile, never in the interaction assertion.
  let keyboardActivation=null;
  document.addEventListener('keydown',event=>{keyboardActivation={target:event.target,key:event.key,activated:false,event};},true);
  document.addEventListener('click',event=>{if(keyboardActivation && (keyboardActivation.target===event.target||keyboardActivation.target.contains(event.target)))keyboardActivation.activated=true;},true);
  document.addEventListener('keyup', event => {
    if(event.defaultPrevented || ![' ','Space','Enter'].includes(event.key))return;
    const node=event.target.closest?.('button,a[href],summary,input[type="checkbox"],input[type="radio"],[role="button"]');
    if(node && !node.disabled && ((node.matches('a[href]') && event.key==='Enter') || (!node.matches('a[href]') && [' ','Space','Enter'].includes(event.key)))) {
      const activation=keyboardActivation;
      setTimeout(()=>{if(!event.defaultPrevented && !activation?.event.defaultPrevented && !activation?.activated)node.click();},0);
    }
  });
  let touchStart=null, touchActivation=null, nativeTouchPointerAt=0;
  const scrollParent=node=>{while(node&&node!==document.documentElement){const style=getComputedStyle(node);if(/auto|scroll/.test(style.overflowY+' '+style.overflow)&&node.scrollHeight>node.clientHeight)return node;node=node.parentElement;}return document.scrollingElement;};
  window.__neyviaDispatchWheel=args=>{
    const target=document.elementFromPoint(args.x,args.y);if(!target)return false;
    const event=new WheelEvent('wheel',{bubbles:true,cancelable:true,clientX:args.x,clientY:args.y,deltaX:args.deltaX||0,deltaY:args.deltaY||0,deltaMode:0});
    if(target.dispatchEvent(event)){const node=scrollParent(target);node?.scrollBy({left:args.deltaX||0,top:args.deltaY||0,behavior:'instant'});}
    return true;
  };
  document.addEventListener('click',event=>{if(touchActivation && (event.target===touchActivation.target||touchActivation.target.contains(event.target)))touchActivation.activated=true;},true);
  let activeTouches=[];
  window.__neyviaDispatchTouch = args => {
    const ending=args.type==='touchEnd'||args.type==='touchCancel';
    const changed=ending?activeTouches:args.touchPoints.map((touch,index)=>({identifier:touch.id??index,clientX:touch.x,clientY:touch.y,pageX:touch.x+scrollX,pageY:touch.y+scrollY,screenX:touch.x,screenY:touch.y}));
    const target=touchStart?.target||(changed[0]&&document.elementFromPoint(changed[0].clientX,changed[0].clientY));
    activeTouches=ending?[]:changed;if(!target)return false;
    const event=new Event(args.type.toLowerCase(),{bubbles:true,cancelable:true});
    Object.defineProperties(event,{touches:{value:activeTouches},targetTouches:{value:activeTouches},changedTouches:{value:changed}});
    target.dispatchEvent(event);return true;
  };
  document.addEventListener('pointerdown',event=>{if(event.pointerType==='touch')nativeTouchPointerAt=Date.now();},true);
  document.addEventListener('touchstart',event=>{
    const touch=event.changedTouches[0];if(!touch)return;
    touchStart={x:touch.clientX,y:touch.clientY,target:event.target,activated:false,native:Date.now()-nativeTouchPointerAt<20};
    touchActivation=touchStart;
    if(!touchStart.native)touchStart.pointerCanceled=!event.target.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,cancelable:true,clientX:touch.clientX,clientY:touch.clientY,pointerId:touch.identifier+1,pointerType:'touch',buttons:1}));
    touchStart.scrollNode=scrollParent(event.target);
    touchStart.lastY=touch.clientY;
  });
  document.addEventListener('touchmove',event=>{
    const touch=event.changedTouches[0];if(touch && touchStart && !touchStart.native)(capture.get(touch.identifier+1)||touchStart.target).dispatchEvent(new PointerEvent('pointermove',{bubbles:true,clientX:touch.clientX,clientY:touch.clientY,pointerId:touch.identifier+1,pointerType:'touch',buttons:1}));
    if(touch&&touchStart?.scrollNode&&!event.defaultPrevented&&!touchStart.pointerCanceled&&getComputedStyle(touchStart.target).touchAction!=='none'){touchStart.scrollNode.scrollBy({top:touchStart.lastY-touch.clientY,behavior:'instant'});touchStart.lastY=touch.clientY;}
  });
  document.addEventListener('touchend',event=>{
    const touch=event.changedTouches[0], start=touchStart;touchStart=null;if(!start||!touch)return;
    if(!start.native)(capture.get(touch.identifier+1)||start.target).dispatchEvent(new PointerEvent('pointerup',{bubbles:true,clientX:touch.clientX,clientY:touch.clientY,pointerId:touch.identifier+1,pointerType:'touch',buttons:0}));
    if(!event.defaultPrevented && Math.hypot(touch.clientX-start.x,touch.clientY-start.y)<10)setTimeout(()=>{if(!start.activated)start.target.click();if(touchActivation===start)touchActivation=null;},0);
  });
  if (!Element.prototype.setPointerCapture) {
    Element.prototype.setPointerCapture = function(id) {
      capture.set(id, this);
      this.dispatchEvent(new PointerEvent('gotpointercapture', {pointerId:id,bubbles:true}));
    };
    Element.prototype.hasPointerCapture = function(id) { return capture.get(id) === this; };
    Element.prototype.releasePointerCapture = function(id) {
      if (capture.get(id) === this) { capture.delete(id); this.dispatchEvent(new PointerEvent('lostpointercapture',{pointerId:id,bubbles:true})); }
    };
    for (const type of ['pointermove','pointerup','pointercancel']) document.addEventListener(type, event => {
      const target = capture.get(event.pointerId);
      if (target && event.target !== target && !event.__neyviaRetargeted) {
        event.stopImmediatePropagation();
        const copy = new PointerEvent(type, event); Object.defineProperty(copy,'__neyviaRetargeted',{value:true});
        target.dispatchEvent(copy);
      }
      // Release after the page's bubbling up/cancel handler has committed.
      // Releasing here in capture phase sends lostpointercapture first and
      // cancels a valid drop before the page receives pointerup.
      if (type !== 'pointermove' && target) Promise.resolve().then(()=>{
        if(capture.get(event.pointerId)===target)target.releasePointerCapture(event.pointerId);
      });
    }, true);
  }
  document.addEventListener('click', event => {
    const anchor = event.target.closest?.('a[href]');
    if (!anchor) return;
    const target = new URL(anchor.href,location.href);
    if (target.origin !== location.origin || target.pathname !== location.pathname || target.search !== location.search || !target.hash) return;
    const node = document.getElementById(decodeURIComponent(target.hash.slice(1))) || document.getElementsByName(target.hash.slice(1))[0];
    if (!node) return;
    event.preventDefault(); node.scrollIntoView({block:'start',behavior:profile.reducedMotion?'instant':'auto'});
    history.pushState(null,'',target.href);
  });
  document.addEventListener('DOMContentLoaded',apply);
  new MutationObserver(apply).observe(document,{childList:true,subtree:true,attributes:true,attributeFilter:['class','data-neyvia-focused']});
  window.__neyviaRenderProfile = {theme:profile.theme,reducedMotion:profile.reducedMotion,
    adapters:['preference-css','focus-css','focus-event-transport','empty-absolute-generated-hit-regions','root-svg-viewport-coordinates','bounded-svg-hit-regions','pointer-capture','mouse-pointer-transport','fragment-navigation','html-input-defaults','dom-touch-transport','dom-wheel-transport','inline-control-hitboxes'],nativeEngine:'obscura'};
})
