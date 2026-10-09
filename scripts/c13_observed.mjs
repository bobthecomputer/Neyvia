// Render-owned measurements. Declarations select a probe; observed frames decide it.
export function correctiveGeometry() {
  const text=[],overflow=[],centering=[];
  const selector=n=>n.id?'#'+n.id:n.closest('[id]')?'#'+n.closest('[id]').id:n.tagName.toLowerCase();
  for(const n of document.querySelectorAll('body *')) {
    if(n.namespaceURI==='http://www.w3.org/2000/svg'&&n.matches('text,tspan')){
      const root=n.closest('svg'),b=root?.getBoundingClientRect(),s=getComputedStyle(n);
      if(b?.width&&b?.height&&s.visibility!=='hidden'&&s.display!=='none')text.push({selector:selector(n),text:n.textContent.trim(),code:false,citation:false});
      continue;
    }
    if(n.closest('script,style,defs,svg')||n.matches('input,textarea'))continue;
    const s=getComputedStyle(n),b=n.getBoundingClientRect();
    if(!b.width||!b.height||s.display==='none'||s.visibility==='hidden')continue;
    const own=[...n.childNodes].filter(x=>x.nodeType===3).map(x=>x.textContent).join(' ').trim();
    if(!own)continue;
    const credit=n.closest('.source,.sources,.citation,.credit,[data-c13-source]');
    const sourceLink=n.closest('a[href]')?.getAttribute('href')||'';
    text.push({selector:selector(n),text:own,code:!!n.closest('code,pre,kbd'),
      citation:!!credit||/^https:\/\/(doi\.org|dl\.acm\.org|gist\.github\.com)\//i.test(sourceLink)});
    const inner=b.width-parseFloat(s.paddingLeft||0)-parseFloat(s.paddingRight||0)-parseFloat(s.borderLeftWidth||0)-parseFloat(s.borderRightWidth||0);
    const available=b.height-parseFloat(s.paddingTop||0)-parseFloat(s.paddingBottom||0);
    const run=document.createElement('span');run.textContent=own;
    run.style.cssText='position:absolute;visibility:hidden;display:inline-block;box-sizing:content-box';
    for(const key of ['fontFamily','fontSize','fontWeight','fontStyle','letterSpacing','lineHeight','whiteSpace','wordBreak','overflowWrap'])run.style[key]=s[key];
    if(s.whiteSpace!=='nowrap'&&s.whiteSpace!=='pre')run.style.maxWidth=Math.max(1,inner+2)+'px';
    document.body.append(run);const measured=run.getBoundingClientRect();run.remove();
    const control=n.closest('button,[role="button"]');
    // Inline glyph bounds omit the line box; comparing them with line-height
    // invents vertical overflow. Buttons and actual boxes retain that check.
    if(measured.width>inner+2||((s.display!=='inline'||control)&&measured.height>available+2))overflow.push({selector:selector(n),text:own.slice(0,100),cause:'text-outside-box',width:measured.width,height:measured.height,availableWidth:inner,availableHeight:available,detail:'Rendered label must fit inside its box including padding'});
  }
  for(const n of document.querySelectorAll('figure svg,[data-c13-center] svg,svg[data-c13-center]')){
    const parent=n.parentElement,s=getComputedStyle(parent),b=n.getBoundingClientRect(),p=parent.getBoundingClientRect();
    if(!b.width||!p.width)continue;
    const expected=n.hasAttribute('data-c13-center')||parent.hasAttribute('data-c13-center')||s.textAlign==='center';
    if(!expected)continue;
    const dx=b.x+b.width/2-(p.x+p.width/2);
    if(Math.abs(dx)>Math.max(3,p.width*.02))centering.push({selector:selector(n),cause:'off-centre-figure',offsetPx:dx,detail:'Align the centered figure with its owning container'});
  }
  return {text,overflow,centering,method:'Obscura rendered glyph runs and container geometry'};
}
export function diagramGeometry() {
  window.__c13DiagramFrontier=[];
  const hits=[],box=n=>{
    const r=n.getBoundingClientRect();if(r.width&&r.height)return {x:r.x,y:r.y,w:r.width,h:r.height};
    const svg=n.closest('svg'),m=svg?.getScreenCTM?.();if(!m||m.b||m.c)return {x:0,y:0,w:0,h:0};
    for(let p=n;p&&p!==svg;p=p.parentElement)if(p.hasAttribute('transform')||getComputedStyle(p).transform!=='none')return {x:0,y:0,w:0,h:0};
    const number=(k,d=0)=>Number(n.getAttribute(k)??d);let x,y,w,h;
    if(n.tagName.toLowerCase()==='text'){
      const css=getComputedStyle(n),size=Number(n.getAttribute('font-size')||n.closest('[font-size]')?.getAttribute('font-size'))||parseFloat(css.fontSize)||16;
      const c=document.createElement('canvas').getContext('2d');c.font=size+'px '+(n.getAttribute('font-family')||n.closest('[font-family]')?.getAttribute('font-family')||css.fontFamily||'sans-serif');
      const metrics=c.measureText(n.textContent);
      // Obscura canvas advances quantize small font sizes; measure a hidden HTML
      // glyph run using the actual renderer and the same unscaled SVG font.
      const run=document.createElement('span');run.textContent=n.textContent;run.style.cssText='position:absolute;visibility:hidden;white-space:nowrap;line-height:1';run.style.fontSize=size+'px';run.style.fontFamily=n.getAttribute('font-family')||n.closest('[font-family]')?.getAttribute('font-family')||css.fontFamily||'sans-serif';run.style.fontWeight=n.getAttribute('font-weight')||css.fontWeight;run.style.fontStyle=css.fontStyle;document.body.append(run);const advance=run.getBoundingClientRect().width;run.remove();
      const ascent=metrics.actualBoundingBoxAscent||size*.8,descent=metrics.actualBoundingBoxDescent||size*.2;
      w=advance;h=ascent+descent;x=number('x');y=number('y')-ascent;
      const anchor=n.getAttribute('text-anchor')||css.textAnchor;if(anchor==='middle')x-=w/2;else if(anchor==='end')x-=w;
    }else if(n.matches('rect')){x=number('x');y=number('y');w=number('width');h=number('height');}
    else if(n.matches('circle,ellipse')){const rx=number(n.matches('circle')?'r':'rx'),ry=number(n.matches('circle')?'r':'ry');x=number('cx')-rx;y=number('cy')-ry;w=2*rx;h=2*ry;}
    else return {x:0,y:0,w:0,h:0};
    return {x:m.a*x+m.e,y:m.d*y+m.f,w:Math.abs(m.a*w),h:Math.abs(m.d*h),method:'Obscura rendered HTML font advance and SVG root coordinates; conservative font ascent/descent if native metrics absent'};
  };
  const contains=(a,b,p=2)=>b.x>=a.x-p&&b.y>=a.y-p&&b.x+b.w<=a.x+a.w+p&&b.y+b.h<=a.y+a.h+p;
  const overlaps=(a,b)=>Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x)>2&&Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y)>2;
  for(const [index,svg] of [...document.querySelectorAll('svg')].entries()){
    const owner=svg.closest('section[id],article[id],figure[id]');
    const id=svg.id?'#'+svg.id:owner?'#'+owner.id+' svg':'svg',viewport=box(svg);
    const diagram=/decision|diagram|flowchart|map/i.test((svg.getAttribute('aria-label')||'')+' '+(svg.querySelector('title')?.textContent||''))||svg.hasAttribute('data-c13-diagram');
    const shapes=[...svg.querySelectorAll('rect,ellipse,circle,polygon')].filter(n=>!n.closest('defs,clipPath')).map(n=>({n,b:box(n)})).filter(s=>s.b.w>8&&s.b.h>8);
    const nodes=[];
    for(const text of svg.querySelectorAll('text')){
      const b=box(text),label=text.textContent.trim();if(!label)continue;
      if(!b.w||!b.h){
        const issue={selector:id,label,cause:'unmeasurable-text',detail:'SVG text geometry unavailable'};
        if(diagram)hits.push(issue);else window.__c13DiagramFrontier.push(issue);
        continue;
      }
      if(!contains(viewport,b))hits.push({selector:id,label,cause:'clipped-svg-text',detail:'Label exceeds SVG viewport',rect:b});
      const cx=b.x+b.w/2,cy=b.y+b.h/2;
      const candidates=shapes.filter(s=>cx>=s.b.x&&cx<=s.b.x+s.b.w&&cy>=s.b.y&&cy<=s.b.y+s.b.h).sort((a,z)=>a.b.w*a.b.h-z.b.w*z.b.h);
      const shape=candidates[0];
      // Whole-figure backgrounds are not diagram nodes.
      if(diagram&&shape&&shape.b.w*shape.b.h<viewport.w*viewport.h*.65){
        const padding=Number(shape.n.getAttribute('rx')||0)*.25*Math.abs(svg.getScreenCTM?.()?.a||1);
        const labelBox={...shape.b,x:shape.b.x+padding,w:shape.b.w-2*padding};
        if(!contains(labelBox,b,0))hits.push({selector:id,label,cause:'label-overflows-node',detail:'Widen node or wrap/shorten label; keep centre and connector aligned',rect:b,node:shape.b});
        if(!nodes.some(n=>n.n===shape.n))nodes.push({...shape,label});
      }
    }
    for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){
      if(overlaps(nodes[i].b,nodes[j].b)&&!contains(nodes[i].b,nodes[j].b)&&!contains(nodes[j].b,nodes[i].b))hits.push({selector:id,cause:'overlapping-nodes',labels:[nodes[i].label,nodes[j].label],detail:'Separate labelled diagram nodes'});
    }
    if(diagram&&nodes.length>=2){
      const m=svg.getScreenCTM?.(),boundary=(p,b)=>{
        const inside=p.x>=b.x&&p.x<=b.x+b.w&&p.y>=b.y&&p.y<=b.y+b.h;
        return inside?Math.min(p.x-b.x,b.x+b.w-p.x,p.y-b.y,b.y+b.h-p.y):Math.hypot(Math.max(b.x-p.x,0,p.x-b.x-b.w),Math.max(b.y-p.y,0,p.y-b.y-b.h));
      };
      for(const link of svg.querySelectorAll('path:not([data-c13-connector]),line:not([data-c13-connector])')){
        if(!m||link.hasAttribute('transform')){hits.push({selector:id,cause:'unmeasurable-connector',detail:'Declare endpoint IDs or use an untransformed connector'});continue;}
        let segments=[];
        if(link.tagName.toLowerCase()==='line')segments=[[{x:Number(link.getAttribute('x1')),y:Number(link.getAttribute('y1'))},{x:Number(link.getAttribute('x2')),y:Number(link.getAttribute('y2'))}]];
        else{
          const d=link.getAttribute('d')||'';if(/[CQASTZ]/i.test(d))continue;
          let current={x:0,y:0},start=null;
          for(const command of d.matchAll(/([MLHVmlhv])([^MLHVmlhv]*)/g)){
            const [type,raw]=[command[1],command[2]],values=raw.trim().split(/[ ,]+/).map(Number),relative=type===type.toLowerCase();
            if(values.some(v=>!Number.isFinite(v)))continue;
            if(type.toUpperCase()==='M'){if(start)segments.push([start,current]);current={x:values[0]+(relative?current.x:0),y:values[1]+(relative?current.y:0)};start={...current};if(values.length===4)current={x:values[2]+(relative?current.x:0),y:values[3]+(relative?current.y:0)};}
            else if(type.toUpperCase()==='L')current={x:values[0]+(relative?current.x:0),y:values[1]+(relative?current.y:0)};
            else if(type.toUpperCase()==='H')current.x=values[0]+(relative?current.x:0);
            else if(type.toUpperCase()==='V')current.y=values[0]+(relative?current.y:0);
          }if(start)segments.push([start,current]);
        }
        for(const ends of segments)for(const local of ends){
          const p={x:m.a*local.x+m.e,y:m.d*local.y+m.f},distance=Math.min(...shapes.map(s=>boundary(p,s.b)));
          if(distance>5)hits.push({selector:id,cause:'misaligned-connector',distance,detail:'Diagram connector endpoint does not meet a measured node edge',point:p});
        }
      }
    }
    // Endpoints are measured only for explicitly identified connectors. An unlabelled
    // decorative path cannot safely be inferred to be a connector.
    for(const link of svg.querySelectorAll('[data-c13-connector]')){
      try{
        const ids=(link.getAttribute('data-c13-connector')||'').split(/\s+/);
        let matrix=link.getScreenCTM?.(),ends;
        if(matrix&&link.getPointAtLength&&link.getTotalLength){
          ends=[link.getPointAtLength(0),link.getPointAtLength(link.getTotalLength())];
        }else{
          matrix=svg.getScreenCTM?.();if(!matrix||matrix.b||matrix.c)throw Error('Connector root mapping unavailable');
          for(let p=link;p&&p!==svg;p=p.parentElement)if(p.hasAttribute('transform')||getComputedStyle(p).transform!=='none')throw Error('Transformed connector needs native geometry');
          if(link.tagName.toLowerCase()==='line')ends=[{x:Number(link.getAttribute('x1')),y:Number(link.getAttribute('y1'))},{x:Number(link.getAttribute('x2')),y:Number(link.getAttribute('y2'))}];
          else{
            const d=link.getAttribute('d')||'';if(!d||/[CQASTZ]/i.test(d))throw Error('Curved connector needs native geometry');
            let current={x:0,y:0},start;
            for(const command of d.matchAll(/([MLHVmlhv])([^MLHVmlhv]*)/g)){
              const type=command[1],values=command[2].trim().split(/[ ,]+/).map(Number),relative=type===type.toLowerCase();
              if(values.some(v=>!Number.isFinite(v)))throw Error('Invalid straight connector coordinates');
              if(type.toUpperCase()==='M'||type.toUpperCase()==='L'){
                if(values.length%2)throw Error('Invalid connector coordinate pairs');
                for(let i=0;i<values.length;i+=2){current={x:values[i]+(relative?current.x:0),y:values[i+1]+(relative?current.y:0)};if(!start)start={...current};}
              }else for(const v of values){if(type.toUpperCase()==='H')current.x=v+(relative?current.x:0);else current.y=v+(relative?current.y:0);}
            }
            if(!start)throw Error('Missing connector start');ends=[start,current];
          }
        }
        ends.forEach((p,i)=>{const n=document.getElementById(ids[i]);if(!n)throw Error('Missing connector endpoint node');
          const point={x:matrix.a*p.x+matrix.c*p.y+matrix.e,y:matrix.b*p.x+matrix.d*p.y+matrix.f},b=box(n);
          const dx=Math.max(b.x-point.x,0,point.x-b.x-b.w),dy=Math.max(b.y-point.y,0,point.y-b.y-b.h);
          const inside=point.x>=b.x&&point.x<=b.x+b.w&&point.y>=b.y&&point.y<=b.y+b.h;
          const distance=inside?Math.min(point.x-b.x,b.x+b.w-point.x,point.y-b.y,b.y+b.h-point.y):Math.hypot(dx,dy);
          if(distance>5)hits.push({selector:id,cause:'misaligned-connector',endpoint:ids[i],distance,detail:'Connector endpoint must meet the node edge'});
        });
      }catch(error){hits.push({selector:id,cause:'unmeasurable-connector',detail:error.message});}
    }
  }
  return hits;
}
export function motionState() {
  const nodes=[...document.querySelectorAll('body,body *')];
  return {
    preference:matchMedia('(prefers-reduced-motion: reduce)').matches,
    palette:[getComputedStyle(document.body).backgroundColor,getComputedStyle(document.body).color,getComputedStyle(document.documentElement).backgroundColor],
    active:typeof document.getAnimations==='function'?document.getAnimations().filter(a=>a.playState==='running').length:null,
    styles:nodes.filter(n=>n.getBoundingClientRect().width>0).slice(0,400).map(n=>{const s=getComputedStyle(n);return [n.id||n.tagName,s.opacity,s.transform,s.backgroundColor,s.color,n.getAttribute('d'),n.getAttribute('cx'),n.getAttribute('x')];})
  };
}
export async function captureMotion({browser,adapter,url,out,fs,path,hash,pause,pointer,routeAssets}){
 const report={frames:[],errors:[],sequences:[],meaningful:0,themeToggle:false};
 for(const reduced of [false,true]){
  const context=await browser.newContext({viewport:{width:1440,height:1000},colorScheme:'light',serviceWorkers:'block'});
  const prefix=reduced?'reduced-motion':'motion';
  try{
   await context.addInitScript({content:`(${adapter})(${JSON.stringify({theme:'light',reducedMotion:reduced,nativeColorScheme:true})});`});
   await context.route('**/*',routeAssets(report));
   const page=await context.newPage();await page.goto(url,{waitUntil:'load',timeout:30000});
   const capture=async(label,offsetMs)=>{
    const file=path.join(out,label+'.png'),state=await page.evaluate(motionState),pixels=await page.screenshot({path:file,timeout:15000});
    return {path:file,sha256:hash(pixels),offsetMs,state};
   };
   const frames=[await capture(prefix+'-0',0)];await pause(650);frames.push(await capture(prefix+'-650',650));
   const changed=frames[0].sha256!==frames[1].sha256;
   if(reduced)report.reduced={frames,changed,preference:frames[0].state.preference,active:frames[1].state.active};
   else{report.frames=frames;report.changed=changed;report.preference=frames[0].state.preference;if(changed)report.meaningful++;}
   const probes=await page.evaluate(()=>[...document.querySelectorAll('[data-c13-theme-toggle],[data-c13-motion-probe],button[aria-label*="theme" i]')].filter(n=>{const r=n.getBoundingClientRect(),css=getComputedStyle(n);return !n.hidden&&r.width>0&&r.height>0&&css.display!=='none'&&css.visibility!=='hidden'&&n.matches('button,input,select,a[href],[role="button"],[role="slider"],[tabindex],[data-c13-action]');}).slice(0,3).map((n,i)=>{if(!n.id)n.id='c13-motion-probe-'+i;return {id:n.id,theme:n.matches('[data-c13-theme-toggle],button[aria-label*="theme" i]')};}));
   for(const probe of probes){
    await page.evaluate(id=>document.getElementById(id).scrollIntoView({block:'center'}),probe.id);await pause(700);
    const label=prefix+'-'+probe.id,seq={id:'#'+probe.id,reduced,theme:probe.theme,frames:[await capture(label+'-before',0)]};
    const r=await page.evaluate(id=>{const r=document.getElementById(id).getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};},probe.id);
    if(probe.theme)await page.evaluate(id=>{
      window.__c13ThemeTrace=[];
      document.getElementById(id).addEventListener('click',()=>{
        const started=performance.now();
        const sample=()=>{const s=getComputedStyle(document.body),r=getComputedStyle(document.documentElement);
          window.__c13ThemeTrace.push({elapsedMs:performance.now()-started,palette:[s.backgroundColor,s.color,r.backgroundColor]});
          if(performance.now()-started<1200&&window.__c13ThemeTrace.length<120)requestAnimationFrame(sample);};sample();
      },{capture:true,once:true});
    },probe.id);
    await pointer(page,'mousePressed',r.x,r.y,true);await pointer(page,'mouseReleased',r.x,r.y);await pause(120);
    seq.frames.push(await capture(label+'-120',120));await pause(530);seq.frames.push(await capture(label+'-650',650));
    seq.changed=seq.frames[0].sha256!==seq.frames[2].sha256;
    seq.intermediate=seq.frames[1].sha256!==seq.frames[0].sha256&&seq.frames[1].sha256!==seq.frames[2].sha256;
    seq.reducedStill=seq.frames[1].sha256===seq.frames[2].sha256;
    if(probe.theme){
      const before=JSON.stringify(seq.frames[0].state.palette),after=JSON.stringify(seq.frames[2].state.palette);
      await pointer(page,'mousePressed',r.x,r.y,true);await pointer(page,'mouseReleased',r.x,r.y);await pause(650);
      seq.return=await capture(label+'-return',1300);
      seq.reversible=before!==after&&JSON.stringify(seq.return.state.palette)===before;
      const middle=JSON.stringify(seq.frames[1].state.palette);
      seq.themePaletteTrace=await page.evaluate(()=>window.__c13ThemeTrace||[]);
      seq.themeIntermediate=(middle!==before&&middle!==after)||seq.themePaletteTrace.some(s=>JSON.stringify(s.palette)!==before&&JSON.stringify(s.palette)!==after);
      if(!reduced)report.themeToggle=seq.reversible&&seq.themeIntermediate;
    }
    if(!reduced&&seq.changed&&seq.intermediate)report.meaningful++;
    report.sequences.push(seq);
   }
  }catch(error){report.errors.push({kind:'motion',reduced,message:error.message});}
  finally{await context.close();}
 }
 return report;
}
