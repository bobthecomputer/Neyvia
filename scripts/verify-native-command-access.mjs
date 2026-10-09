import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,readFileSync,existsSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';

const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const fixture=mkdtempSync(path.join(tmpdir(),'neyvia-command-access-'));
const python=resolveNeyviaPython(repo).python;
function call(mode,tool,args,action,extra=[]) {
  const request={jsonrpc:'2.0',id:1,method:'tools/call',params:{name:'neyvia.native.call',arguments:{toolId:tool,arguments:args,actionId:action}}};
  const result=spawnSync(python,['-m','grant_agent.neyvia_mcp_stdio','--root',fixture,'--session-id','command-access',
    '--permission-mode',mode,...extra],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},
    input:JSON.stringify(request)+'\n',encoding:'utf8',timeout:45000});
  assert.equal(result.status,0,result.stderr);
  const response=JSON.parse(result.stdout.trim().split(/\r?\n/).at(-1));
  assert.equal(response.error,undefined,JSON.stringify(response.error));
  return response.result.structuredContent;
}
try {
  const command="from pathlib import Path; p=Path('once.txt'); p.write_bytes((p.read_bytes() if p.exists() else b'')+b'once\\n'); print('EXECUTED')";
  for(const mode of ['read-only','workspace']) {
    const denied=call(mode,'terminal.exec',{shell:'python',command},'deny-'+mode);
    assert.equal(denied.ok,false);
    assert.equal(existsSync(path.join(fixture,'once.txt')),false);
  }
  const readonly=call('full-access','terminal.exec',{shell:'python',command},'readonly-override',['--read-only','--native-mutation-tool','terminal.exec']);
  assert.equal(readonly.ok,false);
  assert.equal(existsSync(path.join(fixture,'once.txt')),false);
  const executed=call('full-access','terminal.exec',{shell:'python',command},'execute-once');
  assert.equal(executed.ok,true,JSON.stringify(executed));
  assert.equal(executed.toolResult.exitCode,0);
  assert.match(executed.toolResult.stdout,/EXECUTED/);
  assert.equal(readFileSync(path.join(fixture,'once.txt'),'utf8'),'once\n');
  const replay=call('full-access','terminal.exec',{shell:'python',command},'execute-once');
  assert.equal(replay.duplicateSuppressed,true);
  assert.equal(readFileSync(path.join(fixture,'once.txt'),'utf8'),'once\n');
  const failure=call('full-access','terminal.exec',{shell:'python',command:'raise SystemExit(7)'},'nonzero');
  assert.equal(failure.ok,false);
  assert.equal(failure.toolResult.exitCode,7);
  const environment=call('read-only','runtime.environment',{},'');
  assert.equal(environment.ok,true);
  assert.equal(path.resolve(environment.result.workspaceRoot),path.resolve(fixture));
  console.log(JSON.stringify({passed:true,transport:'actual stdio MCP',readOnlyDenied:true,workspaceDenied:true,
    explicitReadOnlyWins:true,fullAccessExecuted:true,stableActionReplaySuppressed:true,nonzeroReported:true,workspaceRootCorrect:true}));
} finally {
  assert(fixture.startsWith(path.join(tmpdir(),'neyvia-command-access-')));
  rmSync(fixture,{recursive:true,force:true});
}
