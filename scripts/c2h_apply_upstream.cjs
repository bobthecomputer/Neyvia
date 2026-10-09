'use strict';
// Resolve only the two context conflicts in Apache-2.0 Obscura PR #1080.
// The Rust client, WHATWG state machine and upstream tests remain upstream code.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const root='.agent_control/C2f/upstream-v0.2.4/obscura-0.2.4';
const p='crates/obscura-js/js/bootstrap.js',file=root+'/'+p,rej=file+'.rej';
const start="if (typeof WebSocket === 'undefined') {",end="if (typeof BroadcastChannel === 'undefined') {";
const patch=fs.readFileSync(rej,'utf8').split(/\r?\n/).filter(l=>l.startsWith('+')||l.startsWith(' ')).map(l=>l.slice(1)).join('\n');
const replacement=patch.slice(patch.indexOf(start),patch.indexOf(end));
if(!replacement.includes('op_ws_connect')||!replacement.includes('op_ws_next'))throw Error('Upstream state machine absent');
const current=fs.readFileSync(file,'utf8');if(!current.includes('drop; no real socket'))throw Error('Expected preserved fork stub');
fs.writeFileSync(file,current.slice(0,current.indexOf(start))+replacement+current.slice(current.indexOf(end)));
const ops=root+'/crates/obscura-js/src/ops.rs',content=fs.readFileSync(ops,'utf8');
const declarations=['create','connect','send','close','next'].map(n=>'        crate::websocket::op_ws_'+n+'(),').join('\n');
if(content.includes('crate::websocket::op_ws_'))throw Error('Duplicate socket declarations');
fs.writeFileSync(ops,content.replace('        op_begin_render_task(),','        op_begin_render_task(),\n'+declarations));
const upstream=fs.readFileSync('.agent_control/C2h/upstream/pr1080.patch');
fs.writeFileSync('scripts/evidence/C2h-upstream-adaptation.json',JSON.stringify({at:new Date().toISOString(),upstream:'https://github.com/h4ckf0r0day/obscura/pull/1080',upstreamCommit:'3e51589f2769dfb58d11fb48436c24cbc29bcc41',license:'Apache-2.0',patchSha256:crypto.createHash('sha256').update(upstream).digest('hex'),conflicts:[{path:p,resolution:'Preserve fork EventSource; replace exactly the WebSocket stub with upstream rejected-hunk additions'},{path:'crates/obscura-js/src/ops.rs',resolution:'Register the five upstream ops after the retained render task op'}],supersededCustomImplementation:'.agent_control/C2h/superseded/custom-websocket.patch',downloadsOver200MB:false},null,2)+'\n');
console.log('Resolved upstream WebSocket state machine and op registration');
