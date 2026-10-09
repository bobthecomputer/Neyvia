// Source-backed token inventory and repeatable consistency review. CL calls this owner.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import postcss from 'postcss';
import {execFileSync} from 'node:child_process';
import {SPRING} from '../web/src/neyvia/next/nxSpring.js';

const root = path.resolve(import.meta.dirname, '..');
const next = path.join(root, 'web/src/neyvia/next');
const reusedAppStyles = new Set(['imagePlaygroundScoped.css','neyviaOfficeSuite.css','neyviaMarketplace.css','NeyviaMessageBody.css','NeyviaPromptEditorDialog.css','neyviaTasteReview.css']);
const tokenFiles = new Set(['nxTokens.css', 'nxThemes.css', 'nxLook.css', 'nxAppSkins.css']);
const digest = value => crypto.createHash('sha256').update(value.replaceAll('\r\n','\n')).digest('hex');
export function inventory() {
  const sources = {}, tokens = {};
  for (const name of ['nxTokens.css', 'nxThemes.css', 'nxLook.css', 'nxAppSkins.css']) {
    const source = fs.readFileSync(path.join(next, name), 'utf8').replaceAll('\r\n','\n');
    sources[`web/src/neyvia/next/${name}`] = digest(source);
    postcss.parse(source).walkDecls(/^--nx-/, d => {
      (tokens[d.prop] ||= []).push({selector: d.parent.selector, value: d.value, source: name, line: d.source.start.line});
    });
  }
  for (const name of ['nxSpring.js', 'nxAppSkinModel.js']) sources[`web/src/neyvia/next/${name}`] = digest(fs.readFileSync(path.join(next,name),'utf8'));
  return {schema: 'neyvia.design-language.v1', sources, tokens, springs: SPRING,
    primitives: 'web/src/neyvia/next/nxPrimitives.jsx', icons: {family: 'Lucide', stroke: 1.75},
    contracts: {textContrast: 4.5, focusContrast: 3, states: ['rest', 'hover', 'press', 'focus-visible', 'disabled', 'loading'],
      motion: 'CSS timing and spring tokens; prefers-reduced-motion always wins',
      roles: 'Amber is running; gold needs a person; error red; accents are actions. App skins preserve their own identity.'}};
}

function files(dir) {
  return fs.readdirSync(dir, {withFileTypes:true}).flatMap(e => e.isDirectory() ? files(path.join(dir,e.name)) : [path.join(dir,e.name)]);
}
const color = /#[\da-f]{3,8}\b|\b(?:rgba?|hsla?|oklch|oklab|lab|lch|color|device-cmyk)\([^)]*\)|\b(?:white|black)\b/ig;
const measure = /(?<![\w-])(?:\d*\.)?\d+(?:px|rem|em)\b/ig;
const time = /(?<![\w-])(?:\d*\.)?\d+(?:ms|s)\b/g;
export function literals(property, value) {
  let stripped=value.replace(/url\([^)]*\)/g,'');
  // A token reference is allowed; a raw fallback can still become the actual
  // style in a reused app. Keep fallback values visible to the audit.
  for(let n=0;n<8&&stripped.includes('var(');n++) stripped=stripped.replace(/var\((?:[^()]|\([^()]*\))*\)/g,m=>{
    const args=m.slice(4,-1);let depth=0;
    for(let i=0;i<args.length;i++){if(args[i]==='(')depth++;else if(args[i]===')')depth--;else if(args[i]===','&&depth===0)return args.slice(i+1);}
    return '';
  });
  if (/^(?:color|background(?:-color|-image)?|border(?:-(?:top|right|bottom|left))?(?:-color)?|outline(?:-color)?|fill|stroke|accent-color|caret-color)$/.test(property)) {
    const hits=[...stripped.matchAll(color)].map(m => ({kind:'colour',severity:'high',literal:m[0]}));
    const keyword=stripped.trim();
    if(!hits.length && /^[a-z]+$/i.test(keyword) && !/^(?:inherit|initial|unset|revert|transparent|currentcolor|none|auto)$/i.test(keyword)) hits.push({kind:'colour',severity:'high',literal:keyword});
    return hits;
  }
  if (/^(?:padding|margin|gap|row-gap|column-gap)(?:-.+)?$/.test(property)) {
    return [...stripped.matchAll(measure)].filter(m => parseFloat(m[0]) !== 0).map(m => ({kind:'spacing',severity:'medium',literal:m[0]}));
  }
  if (/^border(?:-.+)?-radius$/.test(property) || property === 'border-radius') {
    return [...stripped.matchAll(measure)].filter(m=>parseFloat(m[0])!==0).map(m=>({kind:'radius',severity:'medium',literal:m[0]}));
  }
  if (property === 'font-size' || property === 'font') return [...stripped.matchAll(measure)].map(m=>({kind:'type',severity:'medium',literal:m[0]}));
  if (/^(?:box-shadow|text-shadow)$/.test(property) && ([...stripped.matchAll(measure)].some(m=>parseFloat(m[0])!==0) || [...stripped.matchAll(color)].length)) {
    return [{kind:'shadow',severity:'medium',literal:value}];
  }
  if (/^(?:transition|animation)(?:-.+)?$/.test(property)) return [...stripped.matchAll(time)].filter(m=>parseFloat(m[0])!==0).map(m=>({kind:'motion',severity:'medium',literal:m[0]}));
  return [];
}

export function review(paths, {ref}={}) {
  const candidates = paths?.length ? paths.map(p=>path.resolve(root,p)) : [...files(next), ...files(path.join(root,'web/src/neyvia')).filter(p=>!p.startsWith(next+path.sep) && (/(?:App|Studio|Preview|Factory|Research|Notes|Files).*\.css$/i.test(path.basename(p)) || reusedAppStyles.has(path.basename(p))))];
  const findings = [], sources = {}, exemptions = [];
  for (const file of [...new Set(candidates)].sort()) {
    if (!/\.(?:css|jsx|js|tsx)$/.test(file) || /(?:\.test\.|providerMarksData|nxAppSkinModel|nxLookModel|Contracts)/.test(file)) continue;
    if (!file.startsWith(root + path.sep)) throw new Error('Review paths must stay inside this worktree');
    const relative = path.relative(root,file).replaceAll('\\','/');
    if (relative.includes('/vendor/')) {exemptions.push({path:relative,reason:'Unmodified third-party terminal renderer; its own source licence and canvas palette'});continue;}
    const source = ref ? execFileSync('git',['show',`${ref}:${relative}`],{cwd:root,encoding:'utf8',windowsHide:true}) : fs.readFileSync(file,'utf8'); sources[relative]=digest(source);
    if (tokenFiles.has(path.basename(file))) exemptions.push({path:relative,reason:'Custom property definitions only; component declarations are reviewed'});
    if (file.endsWith('.css')) {
      postcss.parse(source).walkDecls(d=> {
        if (d.prop.startsWith('--')) return;
        for (const hit of literals(d.prop,d.value)) findings.push({...hit,path:relative,line:d.source.start.line,selector:d.parent.selector,property:d.prop,value:d.value});
      });
    } else {
      const pattern = /\b(color|backgroundColor|borderRadius|fontSize|boxShadow|gap|rowGap|columnGap|padding(?:Top|Right|Bottom|Left)?|margin(?:Top|Right|Bottom|Left)?|transitionDuration|animationDuration)\s*:\s*("[^"\n]*"|'[^'\n]*'|\d+(?:\.\d+)?)/g;
      for (const match of source.matchAll(pattern)) {
        const prop=match[1].replace(/[A-Z]/g,c=>'-'+c.toLowerCase());
        let value=match[2].replace(/^["']|["']$/g,'');
        if (/^\d/.test(value)) value += 'px';
        for(const hit of literals(prop,value)) findings.push({...hit,path:relative,line:source.slice(0,match.index).split('\n').length,selector:'inline style',property:prop,value});
      }
    }
  }
  findings.sort((a,b)=>['high','medium'].indexOf(a.severity)-['high','medium'].indexOf(b.severity)||a.path.localeCompare(b.path)||a.line-b.line);
  const bySeverity = Object.fromEntries(['high','medium'].map(s=>[s,findings.filter(f=>f.severity===s).length]));
  const byKind = Object.fromEntries(['colour','spacing','radius','type','shadow','motion'].map(k=>[k,findings.filter(f=>f.kind===k).length]));
  return {schema:'neyvia.style-review.v1',ref:ref||'working-tree', scope:'New Neyvia shell and named application CSS/inline styles; custom-property definitions, geometry, canvas/data palettes and JS spring physics are outside literal-consistency counts',sources,exemptions,total:findings.length,bySeverity,byKind,findings};
}

export function designMarkdown(spec=inventory()) {
  const groups = ['font','fs','r-','space','fast','med','snappy','settle','drift','ease','spring','lift','stroke','control'];
  const selected=Object.entries(spec.tokens).filter(([key])=>groups.some(g=>key.includes(g)));
  return `# Neyvia design language\n\nGenerated from nxTokens.css, nxThemes.css, nxLook.css, nxAppSkins.css and the spring/app-skin models by scripts/design_review.mjs. Edit the owners, then regenerate.\n\nUse nxPrimitives.jsx for buttons, fields, segmented choices, menus and dialogs. Lucide icons use one consistent stroke. Keep each app's skin; the shell's green does not paint every app green.\n\nUse semantic CSS variables for colours, spacing, type, shape, shadows and timing. Amber means running, gold needs a person, red means an error. Enabled body, muted and status text must meet 4.5:1 against every actual surface/state; focus indicators need 3:1.\n\nEvery interactive component has rest, hover, press, focus-visible and disabled states. Loading is explicit when an action is pending. Preserve accessible names, roles, keyboard behaviour and reduced motion. Disable interactions while disabled, not only their appearance.\n\nThe complete selector-aware inventory is in config/neyvia_design_language.json. For an App Factory app, copy DESIGN.md and the token stylesheet, keep attribution for reused library source, and review that app's actual CSS rather than the shell's CSS.\n\n| Token | Values and scope |\n|---|---|\n${selected.map(([key,rows])=>`| \`${key}\` | ${rows.map(r=>`\`${r.value}\` (${r.selector})`).join('; ')} |`).join('\n')}\n\nTheme colours are separate for Forest (dark), Morning (light), Sunset and Night Green. Use the colour inventory's selector values, never interpolate between unrelated text and surface colours. App skins own their paired light/dark palettes.\n`;
}

if (process.argv[1] === import.meta.filename) {
  const mode = process.argv[2] || 'review';
  if(!['review','spec','gate'].includes(mode)) throw new Error('Choose review, spec or gate');
  const destination = process.argv[3];
  const args=process.argv.slice(4), ref=args.find(a=>a.startsWith('--ref='))?.slice(6);
  const value = mode === 'spec' ? inventory() : review(args.filter(a=>!a.startsWith('--ref=')), {ref});
  if(destination) {fs.mkdirSync(path.dirname(path.resolve(destination)),{recursive:true});fs.writeFileSync(destination,JSON.stringify(value,null,2)+'\n');}
  if(mode==='spec') fs.writeFileSync(path.join(root,'DESIGN.md'),designMarkdown(value));
  console.log(JSON.stringify(mode==='spec'?{tokens:Object.keys(value.tokens).length,sources:value.sources}:{total:value.total,bySeverity:value.bySeverity,byKind:value.byKind}));
  if(mode==='gate') {
    const saved=JSON.parse(fs.readFileSync(path.join(root,'config/neyvia_design_language.json'),'utf8'));
    const current=inventory();
    const drift=JSON.stringify(saved)!==JSON.stringify(current)||fs.readFileSync(path.join(root,'DESIGN.md'),'utf8').replaceAll('\r\n','\n')!==designMarkdown(current);
    const springMismatch=Object.entries(SPRING).filter(([name,spring])=>current.tokens[`--nx-${name}`]?.some(row=>parseFloat(row.value)!==spring.visualDuration*1000));
    const invalidTiming=Object.keys(value.sources).filter(p=>p.endsWith('.css') && /-var\(/.test(fs.readFileSync(path.join(root,p),'utf8')));
    const doubleTextScale=Object.keys(value.sources).filter(p=>p.endsWith('.css') && /calc\(var\(--nx-fs[^)]*\) \* var\(--nx-ts\)\)/.test(fs.readFileSync(path.join(root,p),'utf8')));
    console.log(JSON.stringify({tokenInventoryCurrent:!drift,clean:value.total===0,springMismatch,invalidTiming,doubleTextScale}));
    if(value.total||drift||springMismatch.length||invalidTiming.length||doubleTextScale.length)process.exitCode=1;
  }
}
