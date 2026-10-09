/* Preserve retained media/fonts when capture URL differs only by fragment. */
const fs=require('fs'),path=require('path'),cp=require('child_process');
const root=path.resolve('.agent_control/C2f/upstream-v0.2.4/obscura-0.2.4'),file='crates/obscura-js/src/runtime.rs',target=path.join(root,file);
const original='        if viewport != state.viewport || base_url != effective_base.as_deref() {';
const replacement=`        // A same-document fragment changes Page's visible URL, but cannot
        // change relative resource resolution. Preserve the prepared CSSOM
        // media/font state instead of falling back to a light raw-DOM paint.
        fn resource_base(value: Option<&str>) -> Option<&str> {
            value.map(|url| url.split('#').next().unwrap_or(url))
        }
        if viewport != state.viewport || resource_base(base_url) != resource_base(effective_base.as_deref()) {`;
let source=fs.readFileSync(target,'utf8');
const before=path.resolve('.agent_control/C2g/fragment-render-before',file),after=path.resolve('.agent_control/C2g/fragment-render-after',file);
if(!source.includes(replacement)){
  if(source.split(original).length!==2)throw Error('Expected exactly one prepared screenshot key comparison');
  fs.mkdirSync(path.dirname(before),{recursive:true});if(!fs.existsSync(before))fs.writeFileSync(before,source);
  source=source.replace(original,replacement);fs.writeFileSync(target,source);
}
fs.mkdirSync(path.dirname(after),{recursive:true});fs.writeFileSync(after,source);
const diff=cp.spawnSync('git',['diff','--no-index','--',before,after],{encoding:'utf8',windowsHide:true});
if(diff.status!==1)throw Error(diff.stderr||'Expected source repair diff');
const patch=diff.stdout.replace(/^diff --git.*$/m,'diff --git a/'+file+' b/'+file).replace(/^---.*$/m,'--- a/'+file).replace(/^\+\+\+.*$/m,'+++ b/'+file);
fs.writeFileSync('scripts/obscura-v024-C2g-fragment-render-key.patch',patch);
console.log(JSON.stringify({patch:'scripts/obscura-v024-C2g-fragment-render-key.patch',file,mechanism:'Ignore only fragment in prepared screenshot resource-base comparison'}));
