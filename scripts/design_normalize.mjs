// Mechanical edits for the owned review scope. The review and git diff remain authoritative.
import fs from 'node:fs';
import path from 'node:path';
import postcss from 'postcss';
import {inventory, review, literals} from './design_review.mjs';

const root=path.resolve(import.meta.dirname,'..');
const mode=process.argv[2];
if(!['scale','colour','shadow','fallback'].includes(mode)) throw new Error('Choose scale, colour, shadow or fallback explicitly');
const spec=inventory();
const spaces=Object.keys(spec.tokens).filter(k=>/^--nx-space-\d+$/.test(k)).map(k=>Number(k.split('-').at(-1))).sort((a,b)=>a-b);
const sizes=[[10,'2xs'],[11,'xs'],[12,'sm'],[13,''],[14,'md'],[14.5,'prose'],[16,'lg'],[20,'xl'],[24,'title'],[32,'hero'],[40,'display'],[48,'display-lg'],[64,'display-xl']];
const radii=[[2,'xxs'],[5,'xs'],[7,'sm'],[10,''],[14,'lg'],[20,'xl'],[28,'2xl'],[999,'pill']];
const nearest=(value,scale)=>scale.reduce((best,x)=>Math.abs(x[0]-value)<Math.abs(best[0]-value)?x:best);
const literalsForFallback=(property,value)=>literals(property,value).length>0;
const skip=new Set(['nxTokens.css']);
const legacyRoles={
  'ny-surface-raised':'raised','ny-border-subtle':'line','ny-text-secondary':'text-2','ny-surface-selected':'accent-soft','ny-text-primary':'text','ny-surface':'bg','ny-text-muted':'muted',
  'ny-accent':'accent','ny-accent-text':'accent-text','ny-accent-ink':'on-accent','ny-text-soft':'text-2','ny-good':'green','ny-bad':'red','ny-warn':'state-caution',
  'ny-faint':'faint','ny-sidebar':'sidebar','ny-hover':'hover','ny-line':'line','ny-line-strong':'line-strong','ny-panel':'panel','ny-text':'text','ny-muted':'muted',
  'neyvia-text':'text','neyvia-muted':'muted','neyvia-accent':'accent','neyvia-line':'line','neyvia-warn':'state-caution','neyvia-surface':'raised','studio-accent':'accent',
  'nx-warn':'state-caution','nx-danger':'red','ny-tree-sun':'tree-sun','ny-tree-leaf':'tree-leaf',
};
const rawColour=/#[\da-f]{3,8}\b|\b(?:rgba?|hsla?)\([^)]*\)|\b(?:white|black)\b/ig;
function semanticColour(literal, property, selector, file) {
  const fixed = {
    '#1d1405':'--nx-ink-on-warm', '#d8d8d0':'--nx-device-text', '#b3261e':'--nx-paper-error',
    'rgba(255, 196, 0, 0.36)':'--nx-mark-user','rgba(255, 196, 0, 0.8)':'--nx-mark-user-line',
    'rgba(80, 150, 255, 0.3)':'--nx-mark-model','rgba(80, 150, 255, 0.9)':'--nx-mark-model-line',
    'rgba(255, 140, 0, 0.28)':'--nx-mark-search','rgba(255, 110, 0, 0.5)':'--nx-mark-search-active',
    'rgba(255, 110, 0, 0.8)':'--nx-mark-search-line','rgba(0, 90, 255, 0.28)':'--nx-paper-selection',
  };
  if(fixed[literal])return `var(${fixed[literal]})`;
  if(/tone-swatch/.test(selector)) {
    const tone=selector.match(/tone-swatch="(\w+)"/)?.[1];
    return `var(--nx-sample-${tone}${['#72e2b5','#2f7c67','#e48d5d'].includes(literal)?'-accent':''})`;
  }
  if(/(?:nx-ms-(?:phone|island|punch|homebutton|earpiece)|af-device-(?:frame|screen|island))/.test(selector)) {
    return `var(--nx-device-${/homebutton/.test(selector)?'key':/earpiece/.test(selector)?'earpiece':/screen/.test(selector)?'screen':'black'})`;
  }
  if(/nx-ms-nopreview/.test(selector))return 'var(--nx-device-text)';
  if(/(?:iframe|nx-pdf-page|nx-pdf-ghost)/.test(selector)&&['white','#fff','#ffffff'].includes(literal.toLowerCase()))return 'var(--nx-paper)';
  if(/nx-pdf-ghost/.test(selector)&&/255, 255, 255/.test(literal))return 'var(--nx-paper-sheen)';
  if(/(?:nx-voice-mic|nx-mic-btn).*is-live/.test(selector))return 'var(--nx-on-error)';
  if(/nx-tray-remove/.test(selector))return property==='color'?'var(--nx-paper)':'var(--nx-scrim)';
  if(/(?:backdrop|layer)$/.test(selector))return 'var(--nx-scrim)';
  if(/(?:device-home|phone-status).*is-light/.test(selector))return 'var(--nx-device-indicator-light)';
  if(/(?:device-home|phone-status)/.test(selector))return 'var(--nx-device-indicator)';
  let rgba;
  if(literal.startsWith('#')) {
    let h=literal.slice(1); if(h.length===3||h.length===4)h=[...h].map(c=>c+c).join('');
    rgba=[0,2,4].map(i=>parseInt(h.slice(i,i+2),16)); rgba.push(h.length===8?parseInt(h.slice(6),16)/255:1);
  } else if(literal==='white'||literal==='black')rgba=Array(3).fill(literal==='white'?255:0).concat(1);
  else if(literal.startsWith('rgb'))rgba=literal.match(/[\d.]+/g).map(Number);
  if(!rgba)return literal;
  const [r,g,b,a=1]=rgba, text=property==='color'||/ink|text|muted|accent$/.test(property), border=/border|line|outline|shadow/.test(property);
  let role;
  if(/(?:error|failed|danger)/.test(selector))role='red';
  else if(/(?:ready|success|passed)/.test(selector))role='green';
  else if(/(?:warn|needs|ask)/.test(selector))role='state-needs';
  else if(Math.max(r,g,b)-Math.min(r,g,b)>40 && Math.max(r,g,b)>100)role=(r>g*1.3&&r>b*1.3)?(g<r*.55?'red':text?'state-running-text':'state-running'):'accent';
  else role=text?(Math.max(r,g,b)>190?'text':Math.max(r,g,b)>135?'text-2':'muted'):border?'line-strong':Math.max(r,g,b)<65?'bg':'raised';
  if(a<1) {
    if(a===0)return 'transparent';
    if(r===g&&g===b&&r>200)role=border?'line':'text';
    if(Math.max(r,g,b)<40)return 'var(--nx-scrim)';
    return `color-mix(in srgb, var(--nx-${role}) ${Math.round(a*100)}%, transparent)`;
  }
  if(border)return `var(--nx-${role==='line-strong'?role:role})`;
  if(!text&&['text','text-2','muted'].includes(role))role='raised';
  return `var(--nx-${role})`;
}
let declarations=0;
for(const relative of Object.keys(review().sources)) {
  if(!relative.endsWith('.css')||skip.has(path.basename(relative))) continue;
  const file=path.join(root,relative), source=fs.readFileSync(file,'utf8'), ast=postcss.parse(source);
  ast.walkDecls(d=>{
    if(d.prop.startsWith('--') && (mode!=='colour'||['nxThemes.css','nxLook.css','nxAppSkins.css'].includes(path.basename(file)))) return;
    const before=d.value;
    if(mode==='fallback') {
      d.value=before.replace(/var\((--[\w-]+)(?:,\s*((?:[^()]|\([^()]*\))*))?\)/g,(all,key,fallback)=>{
        const role=legacyRoles[key.slice(2)];
        if(role && fallback && literalsForFallback(d.prop,fallback))return `var(--nx-${role==='accent' && d.prop==='color'?'accent-text':role})`;
        if(!fallback||!literalsForFallback(d.prop,fallback))return all;
        if(key==='--nx-row-pad')return `var(${key}, var(--nx-space-${Math.round(parseFloat(fallback))}))`;
        if(key==='--amp-ms'||key==='--nx-send-ms')return `var(${key}, var(--nx-${key==='--amp-ms'?'undo-window':'progress-duration'}))`;
        if(spec.tokens[key])return `var(${key})`;
        throw new Error(`Unknown fallback owner ${key}: ${relative}`);
      });
      if(d.value!==before)declarations++;
      return;
    }
    // Preserve complete var() expressions and fallbacks; nested tokens are already a contract.
    const vars=[];
    let value=before.replace(/var\((?:[^()]|\([^()]*\))*\)/g,m=>`__TOKEN_${vars.push(m)-1}__`);
    if(mode==='scale' && /^(padding|margin|gap|row-gap|column-gap)(-.+)?$/.test(d.prop)) {
      value=value.replace(/(-?)(\d*\.?\d+)(px|rem|em)\b/g,(all,sign,n,unit)=>{
        const amount=Number(n)*(unit==='px'?1:16);
        if(amount===0) return '0';
        const step=nearest(amount,spaces.map(v=>[v]))[0];
        if(amount>96||Math.abs(step-amount)>Math.max(1,amount*.15)) return all;
        const token=`var(--nx-space-${step})`;
        return sign?`calc(-1 * ${token})`:token;
      });
    }
    if(mode==='scale' && (/^border(?:-.+)?-radius$/.test(d.prop)||d.prop==='border-radius')) {
      value=value.replace(/(\d*\.?\d+)(px|rem|em)\b/g,(all,n,unit)=>{
        const amount=Number(n)*(unit==='px'?1:16);
        if(amount===0)return '0';
        const role=nearest(amount>=100?999:amount,radii)[1];
        return `var(--nx-r${role?'-'+role:''})`;
      });
    }
    if(mode==='scale' && (d.prop==='font-size'||d.prop==='font')) {
      value=value.replace(/(\d*\.?\d+)(px|rem|em)\b/g,(all,n,unit)=>{
        const role=nearest(Number(n)*(unit==='px'?1:16),sizes)[1];
        return `var(--nx-fs${role?'-'+role:''})`;
      });
    }
    if(mode==='scale' && /^(transition|animation)(-.+)?$/.test(d.prop)) {
      const loop=/\binfinite\b/.test(value);
      value=value.replace(/(-?)(\d*\.?\d+)(ms|s)\b/g,(all,sign,n,unit)=>{
        const ms=Number(n)*(unit==='s'?1000:1);
        const token=ms===0?'none':ms===1?'reduced':d.prop.endsWith('delay')?(ms<=60?'stagger':ms<=90?'feedback-delay':'delay'):
          loop?(ms>10000?'ambient-cycle':ms<=1000?'spin':ms<=1900?'pulse':'breathe'):
          ms<=180?'fast':ms<=210?'med':ms<=250?'snappy':'settle';
        return sign?`calc(-1 * var(--nx-${token}))`:`var(--nx-${token})`;
      });
      value=value.replace(/(?<![\w-])ease(?:-out|-in-out|-in)?\b/g,`var(--nx-${loop?'ease-loop':'ease'})`);
    }
    if(mode==='colour') {
      const selector=d.parent.selector||'';
      if(d.prop==='background'&&/^(?:linear-gradient\(160deg, #(?:3a3c3f|4a4d50))/.test(value))value=`var(--nx-device-metal${value.includes('#4a4d50')?'-android':''})`;
      else if(d.prop==='background'&&/radial-gradient\(circle at 40% 38%/.test(value))value='var(--nx-device-camera)';
      else value=value.replace(rawColour,c=>semanticColour(c,d.prop,selector,path.basename(file)));
    }
    if(mode==='shadow' && /^(box-shadow|text-shadow)$/.test(d.prop)) {
      const selector=d.parent.selector||'';
      if(/(?:nx-ms-phone|af-device-frame)/.test(selector))value='var(--nx-device-shadow)';
      else if(/nx-ms-homebutton/.test(selector))value='var(--nx-device-key-shadow)';
      else if(/nx-ms-earpiece/.test(selector))value='var(--nx-device-earpiece-shadow)';
      else if(/nx-pdf-page/.test(selector))value=`var(--nx-paper-shadow${selector.includes('light')?'-light':''})`;
      else if(/nx-pdf-ghost/.test(selector))value='var(--nx-paper-shadow-light)';
      else if(d.prop==='text-shadow')value='none';
      else {
        // Cast shadows use the shared depth scale. Rings keep their semantic colour.
        const numbers=[...value.matchAll(/(-?\d*\.?\d+)px/g)].map(m=>Math.abs(Number(m[1])));
        if(numbers.some(n=>n>9))value=`var(--nx-lift-${Math.max(...numbers)<=12?1:Math.max(...numbers)<=32?2:3})`;
        else value=value.replace(/(-?)(\d*\.?\d+)px/g,(all,negative,n)=>{
          const role=({'1':'stroke','1.5':'stroke-icon','2':'stroke-strong','3':'ring','4':'halo','5':'space-5','6':'halo-wide','7':'space-7','8':'halo-pulse','9':'halo-max'})[n];
          if(!role)return all;
          return negative?`calc(-1 * var(--nx-${role}))`:`var(--nx-${role})`;
        });
      }
    }
    value=value.replace(/__TOKEN_(\d+)__/g,(_,n)=>vars[Number(n)]);
    if(mode==='scale' && (d.prop==='font-size'||d.prop==='font')) value=value.replace(/calc\((var\(--nx-fs(?:-[\w]+)?\)) \* var\(--nx-ts\)\)/g,'$1');
    if(value!==before) {d.value=value;declarations++;}
  });
  const updated=ast.toString();
  if(updated!==source) fs.writeFileSync(file,updated);
}
console.log(JSON.stringify({batch:mode,changedDeclarations:declarations}));
