'use strict';
const fs=require('node:fs'),cp=require('node:child_process'),crypto=require('node:crypto');
const [buildPath,out]=process.argv.slice(2),hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
if(!buildPath||!out||fs.existsSync(out))throw Error('Completed build and fresh receipt required');
const build=JSON.parse(fs.readFileSync(buildPath));if(build.exitCode!==0||build.cargoNetwork!==false||build.stealth!==false||hash(build.testBinary.path)!==build.testBinary.sha256)throw Error('Verified offline test artifact required');
const exe=build.testBinary.path,list=cp.execFileSync(exe,['--list'],{windowsHide:true,encoding:'utf8'}),names=list.split(/\r?\n/).filter(l=>l.endsWith(': test')).map(l=>l.slice(0,-6));if(names.length!==13)throw Error('Expected all 13 upstream WebSocket integration cases');
const report={schema:'neyvia.C2h.upstream-websocket-tests@1',at:new Date().toISOString(),upstream:'https://github.com/h4ckf0r0day/obscura/pull/1080',buildReceipt:buildPath,buildReceiptSha256:hash(buildPath),binary:build.testBinary,ports:[48734,48735,48736],isolation:'One OS process per test; cargo-nextest unavailable; no shared V8 isolate or fixture port concurrency',tests:[]};
const save=()=>fs.writeFileSync(out,JSON.stringify(report,null,2)+'\n');
for(const name of names){const t=performance.now(),r=cp.spawnSync(exe,[name,'--exact','--nocapture'],{windowsHide:true,encoding:'utf8',timeout:60000});report.tests.push({name,code:r.status,ms:performance.now()-t,passed:r.status===0,error:r.error?.message,stdout:r.stdout?.slice(-2500),stderr:r.stderr?.slice(-1500)});save();console.log(JSON.stringify({name,passed:r.status===0}));}
report.passed=report.tests.every(t=>t.passed);report.finishedAt=new Date().toISOString();save();if(!report.passed)process.exitCode=1;
