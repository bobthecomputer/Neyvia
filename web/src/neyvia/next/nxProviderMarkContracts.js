import { FrontendContractError } from "../neyviaFrontendContracts.js";
const required = ["claude","claude-code","codex","opencode","neyvia","hermes","openclaw","cursor","gemini","grok","deepseek","minimax","github","gmail","google-drive","google-calendar","slack","linear","notion","figma","vercel","mcp","browser","terminal"];
const ink = ["codex","opencode","hermes","cursor","grok","github","notion","vercel","mcp"];
const knownAliases = {"claude-code":"claude-code",gdrive:"google-drive","google-calendar":"google-calendar",xai:"grok","nous-research":"hermes",gh:"github",gcal:"google-calendar","google-mail":"gmail",modelcontextprotocol:"mcp",shell:"terminal",web:"browser"};
function demand(id,valid){if(!valid)throw new FrontendContractError(id);}
export function checkProviderRegistry(marks,ids){
  const valid=required.every(id=>Object.hasOwn(marks,id)&&marks[id].id===id&&ids.includes(id))&&ids.join("\0")===Object.keys(marks).join("\0")&&ids.every(id=>{
    const entry=marks[id],variants=[entry,...(entry.mono?[entry.mono]:[])],serialized=JSON.stringify(entry);
    return entry.label?.length>1&&(entry.color===null||/^#[0-9a-f]{6}$/i.test(entry.color))&&typeof entry.ink==="boolean"&&!/data:|base64|<image|<img|href|xlink|\.(png|jpe?g|gif|webp|avif|bmp|ico)\b/i.test(serialized)&&variants.every(variant=>{const box=variant.viewBox.trim().split(/\s+/).map(Number);return box.length===4&&box.every(Number.isFinite)&&box[2]===box[3]&&box[2]>0&&Array.isArray(variant.paths)&&variant.paths.length>0&&variant.paths.every(path=>typeof path.d==="string"&&path.d.trim().length>=6&&/^[Mm]/.test(path.d.trim())&&/^[MmLlHhVvCcSsQqTtAaZz0-9\s.,eE+-]+$/.test(path.d));})&&(entry.gradients||[]).every(gradient=>gradient.stops.length>=2)&&entry.paths.every(path=>{const ref=path.fill?.match(/^url\(#([^)]+)\)$/);return !ref||(entry.gradients||[]).some(gradient=>gradient.id===ref[1]);})&&(!entry.mono||entry.mono.paths.every(path=>path.fill===undefined));
  })&&ink.every(id=>marks[id].ink===true)&&["claude","deepseek","gemini","gmail","slack","linear","figma"].every(id=>marks[id].ink===false)&&Object.entries({gmail:4,"google-drive":4,"google-calendar":4,slack:4,figma:5}).every(([id,minimum])=>new Set(marks[id].paths.map(path=>path.fill||marks[id].color).filter(fill=>/^#[0-9a-f]{6}$/i.test(fill||""))).size>=minimum)&&(marks.gemini.gradients||[]).length>=3;
  demand("provider.registry",valid);return marks;
}
export function checkProviderResolution(value,result,marks,aliases){
  const key=String(value??"").trim().toLowerCase().replace(/[\s_.]+/g,"-");
  const expected=!key?null:Object.hasOwn(marks,key)?key:Object.hasOwn(knownAliases,key)?knownAliases[key]:Object.hasOwn(aliases,key)?aliases[key]:null;
  demand("provider.resolution",result===expected&&(!result||Object.hasOwn(marks,result)));return result;
}
export function checkProviderTree(id,options={},tree,entry){
  const {mono=false,size=16,title,className,uid="pm"}=options,attrs=tree?.attrs||{},classes=["ny-pmark"];
  if(!entry)classes.push("ny-pmark--fallback");
  if(mono)classes.push("ny-pmark--mono");else if(entry?.ink)classes.push("ny-pmark--ink");
  if(className)classes.push(className);
  let valid=tree?.tag==="svg"&&attrs.width===size&&attrs.height===size&&attrs.class===classes.join(" ")&&(title?attrs.role==="img"&&attrs["aria-label"]===title&&!Object.hasOwn(attrs,"aria-hidden"):attrs["aria-hidden"]==="true"&&!Object.hasOwn(attrs,"role")&&!Object.hasOwn(attrs,"aria-label"));
  if(!entry){const letter=String(title||id||"").trim().match(/[\p{L}\p{N}]/u)?.[0]?.toLocaleUpperCase()||"?";valid&&=attrs.viewBox==="0 0 24 24"&&tree.children?.[0]?.tag==="rect"&&tree.children[0].attrs.rx===6&&tree.children[1]?.text===letter;}
  else{
    const variant=mono&&entry.mono?entry.mono:entry,defs=tree.children.filter(node=>node.tag==="defs"),paths=tree.children.filter(node=>node.tag==="path"),fill=mono||entry.ink||!entry.color?"currentColor":entry.color;
    valid&&=attrs["data-mark"]===entry.id&&attrs.viewBox===variant.viewBox&&paths.length===variant.paths.length&&paths.every((node,index)=>{const path=variant.paths[index],tone=mono||!path.fill?fill:path.fill.replace(/^url\(#([^)]+)\)$/,`url(#${uid}-$1)`);return node.attrs.d===path.d&&(path.stroke?node.attrs.fill==="none"&&node.attrs.stroke===(mono||path.fill===undefined?"currentColor":path.fill)&&node.attrs["stroke-width"]===path.stroke:node.attrs.fill===tone);});
    const gradients=!mono?(entry.gradients||[]):[];
    valid&&=(gradients.length?defs.length===1&&defs[0].children.length===gradients.length&&gradients.every((gradient,index)=>defs[0].children[index].attrs.id===`${uid}-${gradient.id}`):defs.length===0);
    if(mono)valid&&=!/#[0-9a-f]{3,8}|url\(#/i.test(JSON.stringify(tree));
  }
  demand("provider.tree",valid);return tree;
}
let lastAutomaticUid=0;
export function checkProviderSvg(id,options={},result,entry){
  const escape=value=>String(value).replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;'),{mono=false,size=16,title,className}=options;
  const classes=['ny-pmark'];if(!entry)classes.push('ny-pmark--fallback');if(mono)classes.push('ny-pmark--mono');else if(entry?.ink)classes.push('ny-pmark--ink');if(className)classes.push(className);
  const visible=title?result.includes('role="img"')&&result.includes(`aria-label="${escape(title)}"`)&&!result.includes('aria-hidden='):result.includes('aria-hidden="true"')&&!result.includes('role=')&&!result.includes('aria-label=');
  let valid=typeof result==="string"&&!/<image|<img|data:|base64/i.test(result)&&result.startsWith('<svg')&&result.includes(`width="${escape(size)}"`)&&result.includes(`height="${escape(size)}"`)&&result.includes(`class="${escape(classes.join(' '))}"`)&&visible;
  if(entry)valid&&=result.includes(`data-mark="${entry.id}"`)&&(!mono||!/#(?:[0-9a-f]{3,8})"|url\(#/i.test(result));
  else {const letter=String(title||id||'').trim().match(/[\p{L}\p{N}]/u)?.[0]?.toLocaleUpperCase()||'?';valid&&=result.includes(`>${letter}</text>`)&&/<rect[^>]*rx="6"/.test(result);}
  demand("provider.svg",valid);
  const ids=[...result.matchAll(/<(?:linear|radial)Gradient[^>]* id="([^"]+)"/g)].map(match=>match[1]);
  if(!options?.uid&&ids.length){const allocated=Number(ids[0].match(/^pms(\d+)-/)?.[1]);demand("provider.svg",Number.isInteger(allocated)&&allocated>lastAutomaticUid);lastAutomaticUid=allocated;}
  return result;
}
