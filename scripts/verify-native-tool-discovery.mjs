import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const root=mkdtempSync(path.join(tmpdir(),'neyvia-discovery-'));
try {
  const code=[
    'import json,sys',
    'from grant_agent.native_tools import NativeToolRegistry',
    'tools=NativeToolRegistry(sys.argv[1])',
    'queries=["Laya browser journey","browser click test","PowerShell Python command execution"]',
    'print(json.dumps({q:[row["name"] for row in tools.search(q,limit=4)] for q in queries}))',
  ].join('\n');
  const response=spawnSync(resolveNeyviaPython(repo).python,['-c',code,root],{
    cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:30000});
  assert.equal(response.status,0,response.stderr);
  const found=JSON.parse(response.stdout);
  assert(found['Laya browser journey'].includes('preview.taste'));
  assert(found['browser click test'].includes('preview.taste'));
  assert(found['PowerShell Python command execution'].includes('terminal.exec'));
  console.log(JSON.stringify({passed:true,found}));
} finally {
  assert(root.startsWith(path.join(tmpdir(),'neyvia-discovery-')));
  rmSync(root,{recursive:true,force:true});
}
