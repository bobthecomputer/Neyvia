'use strict';
// Portable delta against the preserved fork, excluding scratch Git registration.
const fs=require('node:fs'),cp=require('node:child_process'),crypto=require('node:crypto');
const cwd='.agent_control/C2f/upstream-v0.2.4/obscura-0.2.4';
const git=args=>cp.execFileSync('git',args,{cwd,windowsHide:true,encoding:'utf8'});
const paths=['Cargo.lock','crates/obscura-js/Cargo.toml','crates/obscura-js/js/bootstrap.js','crates/obscura-js/src/lib.rs','crates/obscura-js/src/ops.rs','crates/obscura-js/src/websocket.rs','crates/obscura-cdp/tests/page_websocket.rs'];
const patch=git(['diff','812ed45','HEAD','--',...paths])+git(['diff','7a65002','bdc862f','--','crates/obscura-cdp/Cargo.toml']);
const p='scripts/obscura-v024-C2h-websocket.patch';fs.writeFileSync(p,patch);
git(['apply','--check','--reverse',require('node:path').resolve(p)]);
const receipt='scripts/evidence/C2h-upstream-adaptation.json',r=JSON.parse(fs.readFileSync(receipt));r.portablePatch={path:p,sha256:crypto.createHash('sha256').update(patch).digest('hex'),reverseCheckPassed:true};r.forkTestRegistrationCommit='bdc862f';r.testDiscoveryGap='Fork autotests=false required explicit [[test]] registration for upstream page_websocket.rs';fs.writeFileSync(receipt,JSON.stringify(r,null,2)+'\n');console.log(JSON.stringify(r.portablePatch));
