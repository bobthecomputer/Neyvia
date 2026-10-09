import fs from 'node:fs';
import path from 'node:path';
import postcss from 'postcss';
const root = path.resolve('web/src');
const sourceFiles = [];
function files(dir) { for (const entry of fs.readdirSync(dir,{withFileTypes:true})) { const item=path.join(dir,entry.name); if(entry.isDirectory()) files(item); else if(/\.(jsx?|tsx?)$/.test(item)) sourceFiles.push(item); } }
files(root);
const source = sourceFiles.map(file=>fs.readFileSync(file,'utf8')).join('\n');
const dynamic = [...source.matchAll(/([a-z][\w-]{3,})\$\{/g)].map(match=>match[1]);
const original = fs.readFileSync('web/src/neyvia/neyviaShell.css','utf8');
const tree = postcss.parse(original);
let before=0,after=0;
tree.walkRules(rule=>{
  before++;
  const kept = postcss.list.comma(rule.selector).filter(selector=>{
    if(/\.fluxos-|\.neyvia-shell(?:-|\b)/.test(selector)) return false;
    const classes=[...selector.matchAll(/\.([a-zA-Z_][\w-]*)/g)].map(match=>match[1]);
    return classes.every(name=> name.startsWith('is-') || source.includes(name) || dynamic.some(prefix=>name.startsWith(prefix)));
  });
  if(!kept.length)rule.remove(); else{rule.selector=kept.join(',\n');after++;}
});
tree.walkDecls(decl=>{ if(decl.prop.startsWith('--fluxos-'))decl.remove(); });
let emptied=true;while(emptied){emptied=false;tree.walkAtRules(rule=>{if(rule.nodes&&!rule.nodes.length){rule.remove();emptied=true;}});}
fs.writeFileSync('web/src/neyvia/next/nxToolShared.css','/* Shared styles required by tools hosted in NxShell. */\n'+tree.toString());
for(const file of sourceFiles.filter(file=>file.includes(path.sep+'next'+path.sep))) {
  let text=fs.readFileSync(file,'utf8').replaceAll('nx-classic','nx-tool').replaceAll('Classic screens','Tool screens').replaceAll('Classic surface','Tool surface').replaceAll('Classic panels','Tool panels').replaceAll('classic screen','tool screen').replaceAll('classic palette','shared palette').replaceAll('classic gold','old gold').replaceAll('CLASSIC_APPS','TOOL_APPS');
  if(file.endsWith('NxToolScreens.jsx'))text=text.replace('../neyviaShell.css','./nxToolShared.css');
  fs.writeFileSync(file,text);
}
const voice='src/grant_agent/neyvia_voice.py';
fs.writeFileSync(voice,fs.readFileSync(voice,'utf8').replaceAll('CLASSIC_APPS','TOOL_APPS').replace('These are implemented classic screens that T8 migrates into the new shell.','These implemented tool screens are hosted by the single shell.'));
fs.writeFileSync('D:/NeyviaRuns/REL/tool-style-prune.json',JSON.stringify({beforeRules:before,retainedRules:after,sourceBytes:original.length,retainedBytes:tree.toString().length},null,2)+'\n');
console.log(JSON.stringify({beforeRules:before,retainedRules:after}));
