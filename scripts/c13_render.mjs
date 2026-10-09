import fs from 'node:fs/promises';
import {diagramGeometry,correctiveGeometry,captureMotion} from './c13_observed.mjs';
import path from 'node:path';
import http from 'node:http';
import https from 'node:https';
import dns from 'node:dns/promises';
import net from 'node:net';
import crypto from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { chromium } from 'playwright';

const hash = value => crypto.createHash('sha256').update(value).digest('hex');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/,'$1')), '..');
export async function startObscura(port, out) {
  const python = process.env.NEYVIA_C13_PYTHON || 'C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe';
  const processHost = spawn(python,[path.join(root,'scripts/c13_obscura_host.py'),'--port',String(port),'--root',path.join(out,'browser')],{windowsHide:true,stdio:['pipe','pipe','pipe']});
  let stderr='';processHost.stderr.on('data',data=>stderr+=String(data).slice(0,4000));
  const connection = await new Promise((resolve,reject)=>{
    const startupMs=Number(process.env.NEYVIA_C13_OBSCURA_STARTUP_MS||20000);
    if(!Number.isFinite(startupMs)||startupMs<1000||startupMs>90000){processHost.kill();reject(new Error('Invalid bounded Obscura startup allowance'));return;}
    let buffer='';const timer=setTimeout(()=>{processHost.kill();reject(new Error('Obscura host startup timeout: '+stderr));},startupMs);
    processHost.once('exit',code=>{clearTimeout(timer);reject(new Error(`Obscura host exited ${code}: ${stderr}`));});
    processHost.stdout.on('data',data=>{buffer+=data;const line=buffer.indexOf('\n');if(line>=0){clearTimeout(timer);try{resolve(JSON.parse(buffer.slice(0,line)));}catch(error){reject(error);}}});
  });
  return {connection,async close(){processHost.stdin.end('{"op":"close"}\n');await new Promise(resolve=>{if(processHost.exitCode!==null)return resolve();const timer=setTimeout(()=>{processHost.kill();resolve();},15000);processHost.once('exit',()=>{clearTimeout(timer);resolve();});});}};
}

export async function pointer(page,type,x,y,pressed=false) {
  const cdp=await page.context().newCDPSession(page);
  try {await cdp.send('Input.dispatchMouseEvent',{type,x,y,button:type==='mouseMoved'?'none':'left',buttons:pressed?1:0,clickCount:type==='mouseMoved'?0:1});}
  finally {await cdp.detach();}
}

export async function activate(page,mode,x,y) {
  if(mode==='touch') {await touch(page,{type:'touchStart',touchPoints:[{x,y}]});await touch(page,{type:'touchEnd',touchPoints:[]});}
  else {await pointer(page,'mousePressed',x,y,true);await pointer(page,'mouseReleased',x,y);}
}
async function touch(page,args) {
  // Obscura accepts CDP touch messages but does not emit DOM events. The explicit
  // render profile implements this missing browser input transport in its engine.
  const applied=await page.evaluate(args=>window.__neyviaDispatchTouch?.(args),args);
  if(!applied)throw Error('engine_gap: touch event transport unavailable');
}
async function prepare(page,id,focus=false,scroll=true) {
  return page.evaluate(({id,focus,scroll})=>{const node=document.getElementById(id)||document.querySelector(id);if(!node)throw Error('Discovered control disappeared');const initial=node.getBoundingClientRect();if(focus||initial.x<0||initial.y<0){if(window.__neyviaFocus)window.__neyviaFocus(node);else node.focus();}if(scroll)node.scrollIntoView({block:'center'});const rect=node.getBoundingClientRect();const hit=document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2);return {x:rect.x,y:rect.y,width:rect.width,height:rect.height,hit:hit?{tag:hit.tagName,id:hit.id,label:hit.textContent?.slice(0,80)}:null,role:node.getAttribute('role'),editable:node.getAttribute('contenteditable'),value:node.value,options:node.options?[...node.options].filter(o=>!o.disabled).map(o=>o.value):[]};},{id,focus,scroll});
}
async function captureReader(page,out,name) {
  const viewport=await page.evaluate(()=>({width:innerWidth,height:innerHeight,total:Math.max(document.body.scrollHeight,document.documentElement.scrollHeight)}));
  if(viewport.total>30000)throw Error('Explicit screenshot height budget exceeded: '+viewport.total);
  const tiles=[];
  // Trigger lazy illustrations at their real reader positions before capture.
  for(let y=0;y<viewport.total;y+=Math.floor(viewport.height*.7)){await page.evaluate(y=>scrollTo(0,y),y);await pause(40);}
  for(let y=0;y<viewport.total;y+=viewport.height){
    await page.evaluate(y=>scrollTo(0,y),y);await pause(80);
    const actualY=await page.evaluate(()=>scrollY),file=path.join(out,`${name}.s${String(tiles.length).padStart(2,'0')}.png`);
    const pixels=await page.screenshot({path:file,timeout:15000});tiles.push({path:file,y:actualY,sha256:hash(pixels)});
  }
  const file=path.join(out,name+'.png'),manifest=path.join(out,name+'.tiles.json');
  await fs.writeFile(manifest,JSON.stringify({width:viewport.width,height:viewport.total,tiles,output:file}));
  await new Promise((resolve,reject)=>{
    const child=spawn(process.env.NEYVIA_C13_PYTHON||'C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe',[path.join(root,'scripts/c13_stitch.py'),'--manifest',manifest],{windowsHide:true,stdio:['ignore','ignore','pipe']});
    let error='';child.stderr.on('data',chunk=>error+=chunk);child.on('error',reject);child.on('exit',code=>code===0?resolve():reject(Error('Screenshot stitch failed: '+error)));
  });
  await page.evaluate(()=>scrollTo(0,0));
  return {path:file,sha256:hash(await fs.readFile(file)),tiles,method:'obscura-reader-walk'};
}
const privateAddress = host => {
  const value=host.replace(/^\[|\]$/g,'');
  if(/(^localhost$|\.(localhost|local|lan|internal)$)/i.test(value))return true;
  if(net.isIP(value)===4)return /^(127\.|0\.|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.|198\.(18|19)\.|2(2[4-9]|[34]\d|5[0-5])\.)/.test(value);
  return net.isIP(value)===6 && (!/^[23][0-9a-f]{0,3}:/i.test(value) || /^2001:db8:/i.test(value));
};
async function publicAsset(url, depth=0) {
  if(depth>5 || url.protocol!=='https:' || privateAddress(url.hostname) || url.username || url.password || url.port && url.port!=='443')throw new Error('Blocked private or unsupported resource origin');
  const addresses=await dns.lookup(url.hostname,{all:true});
  if(!addresses.length || addresses.some(a=>privateAddress(a.address)))throw new Error('Blocked private resource address');
  const address=addresses[0];
  return new Promise((resolve,reject)=>{
    const request=https.get(url,{headers:{'accept-encoding':'identity','user-agent':'Mozilla/5.0 C13 Headless'},lookup:(_hostname,options,callback)=>options.all?callback(null,[address]):callback(null,address.address,address.family)},response=>{
      if([301,302,303,307,308].includes(response.statusCode)&&response.headers.location){response.resume();publicAsset(new URL(response.headers.location,url),depth+1).then(resolve,reject);return;}
      const max=20*1024*1024;
      if(Number(response.headers['content-length']||0)>max){response.destroy();reject(new Error('External asset exceeds 20 MB bounded resource budget'));return;}
      const chunks=[];let size=0;
      response.on('data',chunk=>{size+=chunk.length;if(size>max){response.destroy();reject(new Error('External asset exceeds 20 MB bounded resource budget'));}else chunks.push(chunk);});
      response.on('error',reject);response.on('end',()=>resolve({status:response.statusCode,headers:Object.fromEntries(Object.entries(response.headers).filter(([key])=>!['transfer-encoding','connection','content-length','set-cookie'].includes(key)).map(([key,value])=>[key,String(value)])),body:Buffer.concat(chunks)}));
    });
    request.setTimeout(15000,()=>request.destroy(new Error('External asset timed out')));request.on('error',reject);
  });
}
// Ignore clocks/animations already changing before activation. Only a stable observed
// field changing after the action constitutes evidence; declarations never do.
function stableChange(earlier, before, after) {
  if (JSON.stringify(earlier) === JSON.stringify(before)) return JSON.stringify(before) !== JSON.stringify(after);
  if (!before || typeof before !== 'object' || !earlier || !after || typeof after !== 'object') return false;
  return Object.keys(before).some(key => stableChange(earlier[key], before[key], after[key]));
}
function observedChanges(earlier,before,after) {
  const compact=value=>{const text=JSON.stringify(value);return text?.length>280?text.slice(0,280)+'…':value;};
  const uniqueIds=snapshot=>{const ids=new Map(),duplicates=new Set();for(const node of snapshot.nodes)if(node.id){if(ids.has(node.id))duplicates.add(node.id);ids.set(node.id,node);}for(const id of duplicates)ids.delete(id);return ids;};
  const earlierIds=uniqueIds(earlier),beforeIds=uniqueIds(before);
  const find=(snapshot,ids,node,index)=>ids.get(node.id)||snapshot.nodes[index];
  const changes=[];
  for(const field of ['text','value','checked','selected','open','aria','geometry','scroll','rect','appearance']) {
    for(const [index,node] of after.nodes.entries()) {
      const prior=find(earlier,earlierIds,node,index),old=find(before,beforeIds,node,index);
      if(prior&&old&&stableChange(prior[field],old[field],node[field]))changes.push({node:node.id?'#'+node.id:node.tag+'@'+index,field,before:compact(old[field]),after:compact(node[field])});
      if(changes.length===12)return changes;
    }
  }
  return changes;
}
const selector = 'button,a[href],input,select,textarea,summary,[role="button"],[role="link"],[role="slider"],[role="checkbox"],[role="radio"],[role="tab"],[role="switch"],[tabindex],[contenteditable="true"],[onclick],[onpointerdown],[onmousedown],[ontouchstart],[data-c13-action],canvas,svg';

function instrument() {
  window.__c13labelGeometry=node=>{const parent=node.parentElement,origin=parent.getBoundingClientRect();return [...parent.querySelectorAll('button,[role="button"]')].slice(0,16).map(n=>{const r=n.getBoundingClientRect();return {id:n.id,label:(n.innerText||'').slice(0,80),rect:[r.left-origin.left,r.top-origin.top,r.width,r.height].map(v=>Math.round(v*10)/10)};});};
  const listeners = new WeakMap();
  const remember = (node,type) => {
    if (/^(click|dblclick|pointer|mouse|touch|key|input|change|drag|scroll|wheel)/.test(type)) {
      const types = listeners.get(node) || new Set(); types.add(type); listeners.set(node, types);
    }
  };
  const add=document.addEventListener;
  for(const proto of [EventTarget.prototype,Node.prototype,Element.prototype,HTMLElement.prototype,Document.prototype,Window.prototype]){
    if(!Object.prototype.hasOwnProperty.call(proto,'addEventListener'))continue;
    const native=proto.addEventListener;
    proto.addEventListener=function(type,...args){remember(this,type);return native.call(this,type,...args);};
  }
  window.__c13listeners = listeners;
  window.__c13identities = new WeakMap();
  window.__c13identityNext = 0;
  window.__c13navigation = [];
  add.call(document, 'click', event => {
    const anchor = event.target.closest?.('a[href]');
    if (anchor && anchor.href && new URL(anchor.href).origin !== location.origin) {
      event.preventDefault(); window.__c13navigation.push(anchor.href);
    }
  }, true);
}

async function inventory(page, journeys={}) {
  return page.evaluate(({selector,journeys}) => {
    window.__neyviaSvgHitGaps?.();
    const cssPath = node => {
      if (node.id && document.querySelectorAll(`#${CSS.escape(node.id)}`).length===1) return `#${CSS.escape(node.id)}`;
      const parts = [];
      while (node && node !== document.documentElement) {
        const tag = node.tagName.toLowerCase();
        const siblings = [...node.parentElement.children].filter(item => item.tagName === node.tagName);
        parts.unshift(`${tag}:nth-of-type(${siblings.indexOf(node) + 1})`); node = node.parentElement;
      }
      return `html>${parts.join('>')}`;
    };
    return [...document.querySelectorAll('*')].filter(node => {
      if(node.hasAttribute('data-neyvia-svg-hit'))return false;
      const rect = node.getBoundingClientRect(), style = getComputedStyle(node);
      const types = [...(window.__c13listeners.get(node) || [])];
      // Move/up delegation parents support a descendant gesture. Clicking the
      // container itself is not an additional advertised control.
      const delegationOnly = types.length && types.every(type => /^(pointer|mouse|touch)(move|up|end|leave|cancel)$/.test(type)) &&
        node.querySelector('[data-c13-action],[role="slider"],[role="button"],button,input,a[href]');
      return node.matches(selector) || types.length && !delegationOnly
        ? rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none' && ((!node.disabled && node.getAttribute('aria-disabled') !== 'true') || Object.hasOwn(journeys,'#'+node.id))
        : false;
    }).filter(node => {
      // Decorative SVGs inside an actual control belong to that control; an unhandled SVG is an illustration.
      if (node.matches('svg,canvas')) return window.__c13listeners.has(node) || node.hasAttribute('tabindex') || node.hasAttribute('data-c13-action') || [...node.attributes].some(a => /^on(click|pointer|mouse|touch)/.test(a.name));
      return true;
    }).map(node => {
      if(!window.__c13identities.has(node))window.__c13identities.set(node,window.__c13identityNext++);
      const id=cssPath(node);
      const pseudo=getComputedStyle(node,'::after'),right=parseFloat(pseudo.right);
      const halo=pseudo.content&&pseudo.content!=='none'&&pseudo.position==='absolute'&&pseudo.pointerEvents!=='none'&&Number.isFinite(right)?Math.max(0,-right):null;
      return { id, identity:`${id}@${window.__c13identities.get(node)}`, tag: node.tagName.toLowerCase(), label: (node.getAttribute('aria-label') || node.innerText || node.name || node.id || node.getAttribute('placeholder') || '').trim().slice(0, 160), type: node.type || '', action: node.getAttribute('data-c13-action'), key:node.getAttribute('data-c13-key'),keySequence:journeys[id]?.actionKeys||null, path:node.getAttribute('data-c13-path'), acquire:node.getAttribute('data-c13-acquire'),halo,labelGeometry:halo!==null||node.hasAttribute('data-c13-acquire')?window.__c13labelGeometry(node):null, target: node.getAttribute('data-c13-target'), assert: journeys[id]?.assert||node.getAttribute('data-c13-assert'), expect: journeys[id]?.expect??node.getAttribute('data-c13-expect'), href: node.matches('a[href]') ? node.href : null, listeners: [...(window.__c13listeners.get(node) || [])] };
    });
  }, {selector,journeys});
}

async function snapshot(page, control) {
  return page.evaluate(({ control }) => {
    const state = node => {
      const rect = node.getBoundingClientRect(), css = getComputedStyle(node);
      const insideControl=node.matches(control.id)||node.closest(control.id);
      const result = { id:node.id||undefined, tag: node.tagName, text: node.children.length ? undefined : (node.textContent || '').trim(), value: node.value, checked: node.checked, selected: node.selected, open: node.open, scroll:node.scrollHeight>node.clientHeight||node.scrollWidth>node.clientWidth?[node.scrollTop,node.scrollLeft]:undefined, aria: [...node.attributes].filter(a => a.name.startsWith('aria-')).map(a => [a.name,a.value]), rect: insideControl&&!control.action?undefined:[rect.x+scrollX,rect.y+scrollY,rect.width,rect.height].map(n => Math.round(n)), appearance: insideControl&&!control.action?undefined:[css.display,css.visibility,css.backgroundColor,css.color,css.opacity,css.transform] };
      if (node.matches('canvas') && (node.matches(control.id) || node.matches(control.target || ':not(*)'))) { try { result.canvas = node.toDataURL(); } catch { result.canvas = 'tainted'; } }
      if (node.namespaceURI==='http://www.w3.org/2000/svg') result.geometry=[...node.attributes].filter(a=>/^(d|points|x|y|x1|x2|y1|y2|cx|cy|r|rx|ry|width|height|transform|viewBox)$/.test(a.name)).map(a=>[a.name,a.value]);
      return result;
    };
    const asserted = control.assert ? document.querySelector(control.assert) : null;
    return { url: location.href, scroll:scrollY, navigation: [...window.__c13navigation], nodes: [...document.body.querySelectorAll('*')].filter(n => !n.matches('script,style')).map(state), assertion: asserted ? { text: asserted.innerText, value: asserted.value, state: state(asserted) } : null };
  }, {control});
}


async function prerequisite(page,control,recipe,result) {
  if(!recipe)return;
  const disabled=()=>page.evaluate(id=>{const n=document.querySelector(id);return !n||n.disabled||n.getAttribute('aria-disabled')==='true';},control.id);
  if(!await disabled())return;
  const before=await snapshot(page,control);
  const delivered=[];
  await prepare(page,recipe.target,true);
  for(const key of recipe.keys){
    await page.keyboard.press(key);delivered.push(key);await pause(40);
    if(!await disabled())break;
  }
  const after=await snapshot(page,control);
  result.prerequisite={target:recipe.target,keys:delivered,enabled:!await disabled(),
    before_sha256:hash(JSON.stringify(before)),after_sha256:hash(JSON.stringify(after)),
    observedChanges:observedChanges(before,before,after),scope:'Actual keyboard preparation; excluded from activation effect'};
  if(!result.prerequisite.enabled)throw Error('Bounded real-input prerequisite did not enable control');
}

async function action(page, control, mode, result={},captureGesture=null) {
  const box = await prepare(page,control.id,mode==='keyboard'||control.tag==='svg'&&!!control.action);
  if (!box) throw new Error('Discovered control disappeared before activation');
  const x = box.x + box.width / 2, y = box.y + box.height / 2;
  const gesture = control.action;
  if (gesture && !['drag','cross','hold','click'].includes(gesture)) throw new Error(`Unsupported declared interaction: ${gesture}`);
  if (gesture && gesture !== 'click') {
    if (mode === 'keyboard') { if(gesture==='hold'){await page.keyboard.down(control.key||'Space');await pause(900);await page.keyboard.up(control.key||'Space');}else {result.keyboardInput=control.keySequence||[control.key||(gesture==='cross'?'Enter':'ArrowRight')];for(const key of result.keyboardInput)await page.keyboard.press(key);} return gesture; }
    // Resolving the endpoint must not scroll the page after the start was measured.
    const target = control.target ? await prepare(page,control.target,false,false) : null;
    let points=null;
    if(control.path){
      let normalized;
      if(control.path.trim().startsWith('['))normalized=JSON.parse(control.path);
      else {
        // R10 Sol's real pages declare absolute SVG viewBox points. Compile
        // this legacy format to the same bounded normalized path, using the
        // actual element's current viewBox rather than assuming CSS pixels.
        if(!/^\s*-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?(?:\s*;\s*-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?)+\s*$/.test(control.path))throw Error('Invalid legacy SVG gesture path');
        const basis=await page.evaluate(id=>{const n=document.getElementById(id)||document.querySelector(id);
          if(n?.tagName.toLowerCase()!=='svg')return null;
          return (n.getAttribute('viewBox')||n.getAttribute('viewbox')||'').trim().split(/[\s,]+/).map(Number);},control.id);
        if(!basis||basis.length!==4||basis.some(n=>!Number.isFinite(n))||basis[2]<=0||basis[3]<=0)throw Error('Legacy gesture path requires a finite actual SVG viewBox');
        const sourcePoints=control.path.split(';').map(p=>p.split(',').map(Number));
        normalized=sourcePoints.map(([u,v])=>[(u-basis[0])/basis[2],(v-basis[1])/basis[3]]);
        result.gesturePathCompilation={sourceEncoding:'legacy-svg-viewbox',viewBox:basis,sourcePoints,normalized};
      }
      if(!Array.isArray(normalized)||normalized.length<2||normalized.length>16||normalized.some(p=>!Array.isArray(p)||p.length!==2||p.some(n=>!Number.isFinite(n)||n<-.25||n>1.25)))throw Error('Invalid bounded data-c13-path: require 2–16 normalized coordinate pairs within -.25..1.25');
      if(normalized[0].some(n=>n<0||n>1))throw Error('Gesture path must start inside the actual control');
      if(result.gesturePathCompilation){
        const m=await page.evaluate(id=>{const n=document.querySelector(id),t=n?.getScreenCTM?.();return t?[t.a,t.b,t.c,t.d,t.e,t.f]:null;},control.id);
        if(!m||m.some(n=>!Number.isFinite(n)))throw Error('Actual SVG gesture requires finite screen CTM');
        result.gesturePathCompilation.screenCTM=m;
        points=result.gesturePathCompilation.sourcePoints.map(([u,v])=>({x:m[0]*u+m[2]*v+m[4],y:m[1]*u+m[3]*v+m[5]}));
      }else points=normalized.map(([u,v])=>({x:box.x+box.width*u,y:box.y+box.height*v}));
    }
    const capturesStart=control.listeners.some(type=>['pointerdown','mousedown','touchstart'].includes(type));
    // A stroke owner must receive its down event; delegated boundary sensors
    // still begin outside so the stroke actually crosses their leading edge.
    const start=points?.[0]||(gesture==='cross'?{x:box.x+(capturesStart?Math.min(8,box.width*.1):-8),y}:{x,y});
    const containsStart=target && start.x>=target.x && start.x<=target.x+target.width && start.y>=target.y && start.y<=target.y+target.height;
    const end = points?.at(-1)||(gesture==='cross'?{x:box.x+box.width+8,y}:target ? { x:target.x+target.width*(containsStart?(start.x<target.x+target.width*.7?.8:.2):.5), y:target.y+target.height/2 } : {x:x+Math.min(80,box.width/3),y:y});
    points ||= [start,end];
    const moves=[];
    if(gesture!=='hold'||target||control.path)for(let segment=1;segment<points.length;segment++)for(let i=1;i<=8;i++){
      const point={x:points[segment-1].x+(points[segment].x-points[segment-1].x)*i/8,y:points[segment-1].y+(points[segment].y-points[segment-1].y)*i/8};
      if(result.gesturePathCompilation){const source=result.gesturePathCompilation.sourcePoints;point.svg=[source[segment-1][0]+(source[segment][0]-source[segment-1][0])*i/8,source[segment-1][1]+(source[segment][1]-source[segment-1][1])*i/8];}
      moves.push(point);
    }
    result.gestureInput={start,end:moves.length?end:start,path:points,target:control.target,moves:moves.length};
    const stroke=async(wait,phase)=>{
      const before=gesture==='hold'?await snapshot(page,control):null;
      const began=Date.now();
      if(phase==='quick-result'){
        // Keep one ordered transport batch, so protocol round trips do not
        // accidentally turn the expert stroke into another long press.
        if(mode==='touch'){
          const messages=[{type:'touchStart',touchPoints:[start]},...moves.map(p=>({type:'touchMove',touchPoints:[p]})),{type:'touchEnd',touchPoints:[]}];
          const applied=await page.evaluate(messages=>messages.every(args=>window.__neyviaDispatchTouch?.(args)),messages);
          if(!applied)throw Error('engine_gap: quick touch stroke transport unavailable');
        }else{
          const cdp=await page.context().newCDPSession(page);
          try{
            const messages=[{type:'mouseMoved',...start,button:'none',buttons:0,clickCount:0},{type:'mousePressed',...start,button:'left',buttons:1,clickCount:1},...moves.map(p=>({type:'mouseMoved',...p,button:'none',buttons:1,clickCount:0})),{type:'mouseReleased',...end,button:'left',buttons:0,clickCount:1}];
            await Promise.all(messages.map(args=>cdp.send('Input.dispatchMouseEvent',args)));
          }finally{await cdp.detach();}
        }
        if(captureGesture)await captureGesture(phase,before,Date.now()-began,{...result.gestureInput,holdMs:0});
        return;
      }
      if(mode==='touch')await touch(page,{type:'touchStart',touchPoints:[start]});
      else {await pointer(page,'mouseMoved',start.x,start.y);await pointer(page,'mousePressed',start.x,start.y,true);}
      if(wait)await pause(wait);
      if(gesture==='hold'&&wait&&captureGesture)await captureGesture('dwell-open',before,Date.now()-began,{start,end:start,moves:0,holdMs:wait});
      let segmentBefore=control.path?await snapshot(page,control):null;
      let release=end;
      for(const [index,originalPoint] of moves.entries()){
        let point=originalPoint;
        if(point.svg){
          const m=await page.evaluate(id=>{const n=document.querySelector(id),t=n?.getScreenCTM?.();return t?[t.a,t.b,t.c,t.d,t.e,t.f]:null;},control.id);
          if(!m||m.some(n=>!Number.isFinite(n)))throw Error('Actual SVG transform became unavailable during stroke');
          const [u,v]=point.svg;point={x:m[0]*u+m[2]*v+m[4],y:m[1]*u+m[3]*v+m[5]};
          (result.gestureInput.deliveredPoints||=[]).push({svg:[u,v],screenCTM:m,...point});release=point;
        }
        if(mode==='touch')await touch(page,{type:'touchMove',touchPoints:[point]});else await pointer(page,'mouseMoved',point.x,point.y,true);
        if(control.path&&(index+1)%8===0&&captureGesture){
          await captureGesture('path-segment-'+((index+1)/8),segmentBefore,Date.now()-began);
          segmentBefore=await snapshot(page,control);
        }
      }
      if(mode==='touch')await touch(page,{type:'touchEnd',touchPoints:[]});else await pointer(page,'mouseReleased',release.x,release.y);
      if(gesture==='hold'&&captureGesture)await captureGesture(phase,before,Date.now()-began,{...result.gestureInput,holdMs:wait});
    };
    await stroke(gesture==='hold'?900:0,'dwell-result');
    if(gesture==='hold'&&(target||control.path))await stroke(0,'quick-result');
    return gesture;
  }
  if(control.listeners.includes('scroll') && !control.listeners.includes('click')) {
    if(mode==='keyboard')await page.keyboard.press(control.key||'PageDown');
    else if(mode==='pointer'){await pointer(page,'mouseMoved',x,y);const applied=await page.evaluate(args=>window.__neyviaDispatchWheel(args),{x,y,deltaY:140});if(!applied)throw Error('engine_gap: wheel event transport unavailable');}
    else {const distance=Math.min(30,box.height/4);await touch(page,{type:'touchStart',touchPoints:[{x,y:y+distance}]});await touch(page,{type:'touchMove',touchPoints:[{x,y:y-distance}]});await touch(page,{type:'touchEnd',touchPoints:[]});}
    return 'scroll';
  }
  if (control.tag === 'select') {
    const options = box.options;
    const current = box.value;
    const next = options.find(value => value !== current); if (next === undefined) throw new Error('Select has no alternative option');
    if(mode!=='keyboard')await activate(page,mode,x,y);
    await page.evaluate(id=>document.querySelector(id).focus(),control.id);
    await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter');
    return 'select';
  }
  if (control.tag === 'input' && control.type === 'file') throw Error('engine_gap: Obscura file upload input requires native file selection support');
  if ((['input','textarea'].includes(control.tag) && !['button','submit','reset','checkbox','radio','range','color','file','hidden'].includes(control.type)) || box.editable === 'true') {
    await activate(page,mode,x,y);
    await page.evaluate(id=>document.querySelector(id).focus(),control.id);
    await page.keyboard.press('ControlOrMeta+A');
    await page.keyboard.type(control.type === 'number' ? '13' : control.type === 'date' ? '2026-10-04' : control.type === 'email' ? 'c13@example.test' : 'C13 verified input');
    await page.keyboard.press('Tab'); return 'input';
  }
  if (control.type === 'range' || control.tag === 'input' && control.type === 'number' || box.role === 'slider') {
    if(mode === 'keyboard') {await page.keyboard.press('ArrowRight');}
    else await activate(page,mode,box.x+box.width*.8,y);
    return 'adjust';
  }
  if(mode!=='keyboard' && (control.acquire!==null&&control.acquire!==undefined || control.halo!==null&&control.halo!==undefined)) {
    const active=await page.evaluate(id=>{const p=getComputedStyle(document.querySelector(id),'::after');return Math.max(0,-parseFloat(p.right)||0);},control.id);
    const requested=control.acquire!==null&&control.acquire!==undefined?Number(control.acquire):null;
    if(requested!==null&&(!Number.isFinite(requested)||requested<0||requested>40))throw Error('Invalid acquisition margin: require 0–40 CSS pixels beyond the right label edge');
    const interior=active>(control.halo||0)?((control.halo||0)+active)/2:null;
    const margin=interior!==null?Math.min(requested??interior,interior):requested||0;
    if(margin>0){
      const point={x:box.x+box.width+margin,y};
      const hit=await page.evaluate(({id,point})=>{const n=document.querySelector(id),h=document.elementFromPoint(point.x,point.y);return {matches:!!h&&(h===n||n.contains(h)),tag:h?.tagName,id:h?.id,label:(h?.innerText||'').slice(0,120)};},{id:control.id,point});
      result.acquisition={point,margin,requestedMaximum:requested,strategy:interior!==null?'Interior of actual expanded hit region, bounded by requested maximum':'Declared outside-label distance; actual hit required',baselineOutset:control.halo,activeOutset:active,visualRect:box,hit};
      result.hit={...hit,outsideLabel:true,margin};
      if(!hit.matches)throw Error('Outside-label acquisition did not hit the claimed control');
      await activate(page,mode,point.x,point.y);
      const geometry=await page.evaluate(id=>window.__c13labelGeometry(document.querySelector(id)),control.id);
      result.acquisition.labelGeometryBefore=control.labelGeometry;
      result.acquisition.labelGeometryAfter=geometry;
      result.acquisition.labelGeometryStable=JSON.stringify(control.labelGeometry)===JSON.stringify(geometry);
      result.acquisition.geometryScope='First sixteen buttons in the same parent, relative to that parent';
      return 'outside-label-acquisition';
    }
  }
  if(mode === 'keyboard') {await page.keyboard.press(control.key || (control.tag === 'a' || control.tag === 'summary' ? 'Enter' : 'Space'));}
  else await activate(page,mode,x,y);
  return 'activate';
}

async function layout(page) {
  return page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    const offenders = [...document.body.querySelectorAll('*')].filter(n => {const r=n.getBoundingClientRect();return r.width>0 && (r.right>width+2 || r.left < -2) && getComputedStyle(n).position!=='fixed';}).map(n=>({tag:n.tagName,id:n.id,width:Math.round(n.getBoundingClientRect().width)})).slice(0,50);
    const sections = [...document.querySelectorAll('section,article,[role="region"]')].map((node,index)=>{
      const rect=node.getBoundingClientRect();const text=(node.innerText||'').trim(); const words=text.split(/\s+/).filter(Boolean).length;
      const meaningfulMedia=node.querySelectorAll('img,canvas,svg,video,table,pre').length;
      return {index,id:node.id,words,area:Math.round(rect.width*rect.height),words_per_10000px:rect.width*rect.height?Number((words*10000/(rect.width*rect.height)).toFixed(2)):0,media:meaningfulMedia,empty:rect.width>100&&rect.height>120&&words<8&&meaningfulMedia===0};
    });
    const regions=[...document.querySelectorAll('header,main,footer,section,article,figure,[id],[class]')].map(n=>{const r=n.getBoundingClientRect();return {selector:n.id?'#'+n.id:n.tagName.toLowerCase(),aliases:[...n.classList].map(c=>'.'+c),section:n.closest('article[id],section[id]')?.id,rect:[r.x+scrollX,r.y+scrollY,r.width,r.height]};}).filter(r=>r.rect[2]>0&&r.rect[3]>0);
    return {overflow:document.documentElement.scrollWidth>width+2,overflow_pixels:Math.max(0,document.documentElement.scrollWidth-width),offenders,sections,regions};
  });
}

export async function inspect({html,out,port,enginePort=port+1,maxControls=500,maxVariantMs=240000,captureOnly=false,referenceOnly=false,probeControl=null,probeViewport='desktop',probeTheme='light',journeys={}}) {
  if (!path.isAbsolute(html) || !path.isAbsolute(out)) throw new Error('--html and --out must be absolute paths');
  if (!Number.isInteger(port) || port<48801 || port>48809) throw new Error('Explicit C13 port must be 48801-48809');
  if (!Number.isInteger(enginePort) || enginePort<48801 || enginePort>48809 || enginePort===port) throw new Error('Distinct explicit C13 engine port must be 48801-48809');
  if(probeControl && !/^#[a-zA-Z][a-zA-Z0-9_-]*$/.test(probeControl))throw Error('Probe requires one bounded element ID selector');
  if(!['desktop','phone'].includes(probeViewport)||!['light','dark'].includes(probeTheme))throw Error('Invalid bounded probe variant');
  for(const [id,recipe] of Object.entries(journeys)){
    if(!/^#[a-zA-Z][a-zA-Z0-9_-]*$/.test(id)||!/^#[a-zA-Z][a-zA-Z0-9_-]*$/.test(recipe.target)||
       !Array.isArray(recipe.keys)||recipe.keys.length<1||recipe.keys.length>8||
       recipe.keys.some(key=>!['Home','End','ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Enter','Space'].includes(key))||
       (recipe.actionKeys&&(!Array.isArray(recipe.actionKeys)||recipe.actionKeys.length<1||recipe.actionKeys.length>8||recipe.actionKeys.some(key=>!['Home','End','ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Enter','Space'].includes(key))))||
       (recipe.assert&&!/^#[a-zA-Z][a-zA-Z0-9_-]*$/.test(recipe.assert)))
      throw Error('Invalid bounded actual-input journey recipe');
  }
  const requiredModes=probeControl?['pointer','touch']:['pointer','keyboard','touch'];
  const started=Date.now(), bytes=await fs.readFile(html);
  const assets=new Map();
  await fs.mkdir(out,{recursive:true});
  const report={schema_version:1,engine:'obscura',scope:probeControl?'bounded-real-control-probe':captureOnly?'reference-capture':'candidate-interactions',html,html_sha256:hash(bytes),port,enginePort,screenshots:[],resources:[],variants:[],errors:[],passed:false,journeyRecipes:journeys,journeyRecipesSha256:hash(JSON.stringify(journeys))};
  report.crossProtocol='Captured stroke owners start inside their left edge; delegated boundary sensors start 8px before it. Move forward to 8px beyond the right edge, then release. An explicit data-c13-path overrides this geometry.';
  const server=http.createServer((req,res)=>{if(req.url==='/'||req.url==='/index.html'){res.writeHead(200,{'content-type':'text/html; charset=utf-8'});res.end(bytes);}else if(req.url==='/favicon.ico'){res.writeHead(204);res.end();}else{res.writeHead(404);res.end('Self-contained C13 HTML: resource absent');}});
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',resolve);});
  let browser,host;
  try {
    host=await startObscura(enginePort,out);
    browser=await chromium.connectOverCDP(host.connection.endpoint,{headers:{Authorization:'Bearer '+host.connection.token}});
    report.engine_executable=host.connection.executable;
    const adapter=await fs.readFile(path.join(root,'src/grant_agent/browser_render_profile.js'),'utf8');
    report.adapter_sha256=hash(adapter);
    report.observer_sha256=hash(await fs.readFile(path.join(root,'scripts/c13_observed.mjs')));
    const routeAssets=variant=>async route=>{
      const url=new URL(route.request().url());
      if(['data:','blob:','about:'].includes(url.protocol)||url.origin===`http://127.0.0.1:${port}`)return route.continue();
      try{if(!assets.has(url.href))assets.set(url.href,publicAsset(url).then(asset=>{report.resources.push({url:url.href,bytes:asset.body.length,sha256:hash(asset.body),status:asset.status});return asset;}));await route.fulfill(await assets.get(url.href));}
      catch(error){variant.errors.push({kind:'blocked_resource',url:url.href,message:error.message});await route.abort('blockedbyclient');}
    };
    for (const viewport of probeControl?[probeViewport]:['desktop','phone']) for (const theme of probeControl?[probeTheme]:['light','dark']) {
      const variant={viewport,theme,controls:[],errors:[],discovered:0,exercised:0,coverage_complete:true};
      report.variants.push(variant);
      const variantStart=Date.now();
      for(const mode of captureOnly?['pointer']:requiredModes) {
        const context=await browser.newContext({viewport:viewport==='desktop'?{width:1440,height:1000}:{width:390,height:844},colorScheme:theme,hasTouch:true,serviceWorkers:'block'});
        await context.addInitScript(instrument);
        await context.addInitScript({content:`(${adapter})(${JSON.stringify({theme,reducedMotion:true,nativeColorScheme:true})});`});
        await context.route('**/*',routeAssets(variant));
        const page=await context.newPage();page.setDefaultTimeout(1500);
        page.on('console',msg=>{if(msg.type()==='error')variant.errors.push({kind:'console',message:msg.text(),mode});});
        page.on('pageerror',error=>variant.errors.push({kind:'page',message:error.message,mode}));
        page.on('requestfailed',request=>variant.errors.push({kind:'request',url:request.url(),message:request.failure()?.errorText,mode}));
        page.on('response',response=>{if(response.status()>=400)variant.errors.push({kind:'http',url:response.url(),message:String(response.status()),mode});});
        try {
          await page.goto(`http://127.0.0.1:${port}/`,{waitUntil:'load',timeout:30000});
          await pause(150);
          await page.evaluate(async()=>{await Promise.allSettled([...document.fonts].map(font=>font.load()));await document.fonts.ready;});
          if(mode==='pointer') {
            Object.assign(variant,await layout(page));
            variant.diagramIssues=referenceOnly?[]:await page.evaluate(diagramGeometry);
            variant.diagramFrontier=referenceOnly?[]:await page.evaluate(()=>window.__c13DiagramFrontier||[]);
            variant.corrective=referenceOnly?null:await page.evaluate(correctiveGeometry);
            variant.capabilities=await page.evaluate(()=>({dark:matchMedia('(prefers-color-scheme: dark)').matches,reduced_motion:matchMedia('(prefers-reduced-motion: reduce)').matches,pointer_capture:typeof Element.prototype.setPointerCapture==='function',profile:window.__neyviaRenderProfile,fonts:[...document.fonts].map(f=>({family:f.family,status:f.status}))}));
            variant.capabilities.acquisitionProbe='Growing interactive ::after regions are probed inside their actual expanded hit geometry and beyond the baseline/visible right edge. data-c13-acquire=N bounds the requested margin to at most 0–40 CSS pixels; measured point and strategy are recorded. Actual hit-testing and delivered input must select the claimed control; declarations are never proof. Touch uses keyboard focus as explicit preparation for a focus-expanded target.';
            variant.capabilities.changedLabelFollowup='A button whose label changes gets one further activation, unless newly available controls must run first. Both observed state effects are required; this verifies save-then-use and reversible controls without unbounded click loops.';
            if(variant.capabilities.dark!==(theme==='dark')||!variant.capabilities.reduced_motion)variant.errors.push({kind:'engine_gap',message:'Obscura preference adapter failed'});
            const fontFailures=variant.capabilities.fonts.filter(f=>f.status!=='loaded');
            if(fontFailures.length)variant.errors.push({kind:'engine_gap',message:'Obscura web font loading failed',fonts:fontFailures});
            const screenshot=await captureReader(page,out,`${viewport}-${theme}`);report.screenshots.push({viewport,theme,variant:`${viewport}-${theme}`,...screenshot});
          }
          if(captureOnly)continue;
          const done=new Set();
          while(true) {
            const controls=(await inventory(page,journeys)).filter(c=>!probeControl||c.id===probeControl);
            const pending=controls.filter(c=>!done.has(c.identity));
            if(!pending.length)break;
            if(done.size+pending.length>maxControls || Date.now()-variantStart>maxVariantMs) {variant.coverage_complete=false;variant.errors.push({kind:'coverage',message:`Explicit interaction budget exhausted: ${done.size} exercised, ${pending.length} pending`,mode});break;}
            for(const control of pending) {
              done.add(control.identity);
              let row=variant.controls.find(c=>c.identity===control.identity);
              if(!row){row={...control,modes:[],dead:false};variant.controls.push(row);}
              const result={mode,action:control.action||'activate',effect:false};
              try {
                await prerequisite(page,control,journeys[control.id],result);
                const gestureFocus=control.tag==='svg'&&!!control.action;
                const box=await prepare(page,control.id,gestureFocus||mode==='keyboard'||mode==='touch'&&(control.acquire!==null&&control.acquire!==undefined||control.halo!==null&&control.halo!==undefined));
                if(gestureFocus)result.coordinatePreparation='Actual SVG focus and scroll before measuring the input path; excluded from activation proof';
                result.hit=box.hit;
                // Hover may itself commit a selection. Establish a real
                // alternative after hover, so clicking is tested from that state.
                if(mode==='pointer'&&box)await pointer(page,'mouseMoved',box.x+box.width/2,box.y+box.height/2);
                const reset=await page.evaluate(id=>{
                  const node=document.querySelector(id);
                  if(!node)return null;
                  const role=node.getAttribute('role');
                  if(role==='tab'&&node.getAttribute('aria-selected')==='true') {
                    const group=node.closest('[role="tablist"]')||node.parentElement;
                    const sibling=[...group.querySelectorAll('[role="tab"]')].find(item=>item!==node&&!item.disabled);
                    if(sibling){sibling.click();return 'selected-tab-sibling';}
                  }
                  if(node.matches('input[type="radio"]')&&node.checked&&node.name){const sibling=[...document.querySelectorAll('input[type="radio"]')].find(item=>item.name===node.name&&item!==node&&!item.disabled);if(sibling){sibling.click();return 'selected-radio-sibling';}}
                  if(node.getAttribute('aria-pressed')==='true'){
                    const sibling=[...node.parentElement.querySelectorAll('button[aria-pressed="false"],[role="button"][aria-pressed="false"]')].find(item=>item!==node&&!item.disabled);
                    if(sibling){sibling.click();return 'pressed-choice-sibling';}
                  }
                  return null;
                },control.id);
                if(reset)result.preparation=reset;
                // Focus/hover styling is preparation, never proof that a control works.
                const earlier=await snapshot(page,control);await pause(100);
                const before=await snapshot(page,control);result.before_sha256=hash(JSON.stringify(before));
                const captureGesture=async(phase,before,elapsedMs,input)=>{
                  const state=await snapshot(page,control),item={phase,elapsedMs,observedChanges:observedChanges(before,before,state)};
                  if(input)item.input=input;
                  if(viewport==='desktop'&&theme==='light'&&mode==='pointer'){
                    const file=path.join(out,`${viewport}-${theme}-action-${variant.controls.indexOf(row)}-${phase}.png`),pixels=await page.screenshot({path:file,timeout:15000});
                    item.screenshot={path:file,sha256:hash(pixels),method:'obscura-gesture-state',regionRect:await page.evaluate(id=>{const n=document.querySelector(id);if(!n)return null;const r=(n.closest('article,section,figure')||n).getBoundingClientRect();return [r.x,r.y,r.width,r.height];},control.id)};
                  }
                  (result.gestureStates ||= []).push(item);
                  return item;
                };
                result.action=await action(page,control,mode,result,captureGesture);await pause(100);
                const after=await snapshot(page,control);result.after_sha256=hash(JSON.stringify(after));result.effect=stableChange(earlier,before,after);
                result.observedChanges=observedChanges(earlier,before,after);
                if(control.assert) {result.assertion=after.assertion;result.effect=!!after.assertion && stableChange(earlier.assertion,before.assertion,after.assertion) && (control.expect===null||control.expect===undefined||String(after.assertion.text??after.assertion.value??'').includes(control.expect));}
                if(!result.effect)result.error='No observed DOM, value, visual layout, canvas, or navigation effect';
                // Ordinary controls can implement research mechanisms too. Retain
                // their actual resulting state, rather than only declared drags.
                if(viewport==='desktop'&&theme==='light'&&mode==='pointer' && (!control.href || control.action || !result.effect)) {
                  const file=path.join(out,`${viewport}-${theme}-action-${variant.controls.indexOf(row)}.png`),pixels=await page.screenshot({path:file,timeout:15000});
                  result.screenshot={path:file,sha256:hash(pixels),method:'obscura-viewport-after-action',regionRect:await page.evaluate(id=>{const n=document.querySelector(id);if(!n)return null;const r=(n.closest('article,section,figure')||n).getBoundingClientRect();return [r.x,r.y,r.width,r.height];},control.id)};
                }
                if(control.tag==='button'&&!control.action){
                  const now=await inventory(page),updated=now.find(c=>c.identity===control.identity);
                  const newlyAvailable=now.filter(c=>!controls.some(old=>old.identity===c.identity));
                  if(updated?.label&&updated.label!==control.label&&!newlyAvailable.length){
                    const followEarlier=await snapshot(page,control);await pause(100);
                    const followBefore=await snapshot(page,control),began=Date.now();
                    await action(page,updated,mode,{},captureGesture);await pause(100);
                    const followAfter=await snapshot(page,control),effect=stableChange(followEarlier,followBefore,followAfter);
                    const item=await captureGesture('changed-label-followup',followBefore,Date.now()-began);
                    item.effect=effect;
                    result.effect=result.effect&&effect;
                    if(!effect)result.error='Changed-label follow-up produced no observed effect';
                  }
                }
              } catch(error) {result.error=error.message;result.status='undecided';variant.coverage_complete=false;}
              row.modes.push(result);
            }
          }
          variant.discovered=variant.controls.length;
        } catch(error) {variant.errors.push({kind:'driver',message:error.message,mode});variant.coverage_complete=false;}
        finally {
          if(!captureOnly){try{const gaps=await page.evaluate(()=>window.__neyviaSvgHitGaps?.()||[]);if(gaps.length){variant.coverage_complete=false;variant.errors.push({kind:'engine_gap',mode,svg:gaps});}}catch(error){variant.errors.push({kind:'engine_gap',mode,message:error.message});}}
          await context.close();
        }
      }
      variant.exercised=variant.controls.filter(c=>c.modes.length===requiredModes.length).length;
      for(const control of variant.controls) {control.dead=control.modes.some(m=>!m.effect&&m.status!=='undecided');control.undecided=control.modes.length!==requiredModes.length||control.modes.some(m=>m.status==='undecided');}
      if(variant.exercised!==variant.discovered)variant.coverage_complete=false;
      variant.passed=captureOnly?report.screenshots.some(s=>s.variant===`${viewport}-${theme}`)&&!variant.errors.length:variant.coverage_complete&&!variant.overflow&&!variant.sections?.some(s=>s.empty)&&!variant.controls.some(c=>c.dead||c.undecided)&&!variant.errors.length;
    }
    if(!captureOnly&&!probeControl)report.motion=await captureMotion({browser,adapter,url:`http://127.0.0.1:${port}/`,out,fs,path,hash,pause,pointer,routeAssets});
    report.passed=report.variants.length===(probeControl?1:4)&&report.variants.every(v=>v.passed&&(!probeControl||v.discovered===1));
  } catch(error) {report.errors.push({kind:'driver',message:error.message});}
  finally {await browser?.close();await host?.close();await new Promise(resolve=>server.close(resolve));}
  report.duration_ms=Date.now()-started;
  await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2)+'\n');return report;
}

if(process.argv[1]&&import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href) {
  const args=Object.fromEntries(process.argv.slice(2).reduce((pairs,arg,index,list)=>arg.startsWith('--')?[...pairs,[arg.slice(2),list[index+1]]]:pairs,[]));
  try {const report=await inspect({html:args.html,out:args.out,port:Number(args.port),enginePort:Number(args['engine-port']||Number(args.port)+1),captureOnly:args['capture-only']==='true',referenceOnly:args['reference-only']==='true',probeControl:args['probe-control']||null,probeViewport:args['probe-viewport']||'desktop',probeTheme:args['probe-theme']||'light',journeys:args.journeys?JSON.parse(await fs.readFile(args.journeys,'utf8')):{}});console.log(JSON.stringify({passed:report.passed,report:path.join(args.out,'report.json'),screenshots:report.screenshots.length,duration_ms:report.duration_ms}));process.exitCode=report.passed?0:1;}
  catch(error){console.error(error.message);process.exitCode=2;}
}
