// Exercise shipped CLI readback with disposable saved quotas and missing CLIs.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
const repo=path.resolve(import.meta.dirname,'..');
const root=path.join(repo,'.agent_control/t21/failure-'+Date.now().toString(36));
const saved=JSON.parse(fs.readFileSync(path.join(repo,'.agent_control/t21/runtime/.neyvia/live-limits.json'),'utf8'));
const folder=path.join(root,'.neyvia');fs.mkdirSync(folder,{recursive:true});
const file=path.join(folder,'live-limits.json');fs.writeFileSync(file,JSON.stringify(saved));
const env=Object.fromEntries(Object.entries(process.env).filter(([key])=>key.toLowerCase()!=='path'&&key!=='NEYVIA_CODEX_APP_SERVER_COMMAND'));
env.PATH=path.join(root,'no-cli');
const python='C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe';
const run=args=>{const child=spawnSync(python,['scripts/read_live_limits.py','--root',root,...args],{cwd:repo,env,windowsHide:true,encoding:'utf8',timeout:60000});
  assert.equal(child.status,0,child.stderr);return JSON.parse(child.stdout);};
const before=saved.limits.map(row=>[row.app,row.window,row.at,row.usedPercent]).sort();
const failed=run([]);
assert.deepEqual(failed.limits.map(row=>[row.app,row.window,row.at,row.usedPercent]).sort(),before);
assert.ok(failed.limits.every(row=>row.stale));
assert.ok(failed.providers.every(provider=>provider.status!=='ready'));
const after=JSON.parse(fs.readFileSync(file,'utf8'));
assert.deepEqual(after.limits.map(row=>[row.app,row.window,row.at,row.usedPercent]).sort(),before);
for(const row of after.limits) row.resetsAt='2020-01-01T00:00:00Z';
after.providers=after.providers.map(provider=>({...provider,status:'ready',error:null}));
fs.writeFileSync(file,JSON.stringify(after));
const expired=run(['--last-known']);
assert.ok(expired.limits.every(row=>row.stale));
assert.deepEqual(expired.limits.map(row=>row.usedPercent),after.limits.map(row=>row.usedPercent));
const evidence={schema:'neyvia.T21.failure-path.v1',at:new Date().toISOString(),passed:true,root,
  missingCliRefresh:{retained:true,stale:true,unchangedObservationTimes:true,providers:failed.providers},
  expiredWindows:{stale:true,percentagesPreserved:true},scope:'Disposable saved quota replay; real shipped CLI processes, no account quota altered'};
fs.writeFileSync(path.join(repo,'.agent_control/t21/failure-receipt.json'),JSON.stringify(evidence,null,2)+'\n');
console.log('Missing CLI retained last-known times/values; expired windows remain stale, never invented 0%');
