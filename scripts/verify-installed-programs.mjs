import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { resolveNeyviaPython } from './resolve-neyvia-python.mjs';

const root = mkdtempSync(path.join(tmpdir(), 'neyvia-installed-programs-'));
const python = resolveNeyviaPython(process.cwd()).python;
const launched = [];
function call(tool, arguments_ = {}) {
  if (tool === 'host.stop') arguments_ = { expectedRevision: 0, ...arguments_ };
  const process_ = spawnSync(python, ['-c',
    'import json,sys\nfrom grant_agent.native_tools import NativeToolRegistry\np=json.load(sys.stdin)\nprint(json.dumps(NativeToolRegistry(sys.argv[1]).call(p["tool"],p["arguments"])))', root],
    { input: JSON.stringify({ tool, arguments: arguments_ }), encoding: 'utf8', env: { ...process.env, PYTHONPATH: path.resolve('src') }, timeout: 15000 });
  assert.equal(process_.status, 0, process_.stderr);
  return JSON.parse(process_.stdout);
}
function ok(tool, args) { const receipt = call(tool, args); assert(receipt.ok, JSON.stringify(receipt)); return receipt.result.session || receipt.result; }
async function until(identity, accepts) {
  for (let attempt = 0; attempt < 40; attempt++) {
    const result = ok('host.status', { sessionId: identity });
    if (accepts(result)) return result;
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  throw new Error(`Session did not reach expected state: ${identity}`);
}
function launch(script, timeoutSeconds = 20) {
  const result = ok('host.launch', { executable: process.execPath, arguments: ['-e', script], timeoutSeconds });
  launched.push(result.sessionId); return result;
}
try {
  const found = ok('host.programs');
  assert.equal(found.installationRequired, false);
  assert(found.programs.some(program => program.path.toLowerCase() === path.resolve(python).toLowerCase()));
  const first = launch('require("fs").writeFileSync("result.txt",process.execPath);console.log("reused",process.cwd());');
  const complete = await until(first.sessionId, result => result.status === 'completed');
  assert.equal(complete.exitCode, 0);
  assert(complete.stdout.includes('reused'));
  assert.equal(readFileSync(path.join(complete.workingDirectory, 'result.txt'), 'utf8'), process.execPath);
  assert.equal(complete.hostAccess, true);
  assert.equal(complete.isolation, 'working-directory');
  assert.equal(complete.installationRequired, false);
  const second = launch('console.log("live output");setInterval(()=>{},1000)');
  assert.notEqual(second.workingDirectory, first.workingDirectory);
  await until(second.sessionId, result => result.status === 'running' && result.stdout.includes('live output'));
  assert(ok('host.stop', { sessionId: second.sessionId }).stopRequested);
  await until(second.sessionId, result => result.status === 'stopped');
  const failed = launch('process.stderr.write("failure proof");process.exit(7)');
  const failure = await until(failed.sessionId, result => result.status === 'failed');
  assert.equal(failure.exitCode, 7); assert(failure.stderr.includes('failure proof'));
  const timed = launch('setInterval(()=>{},1000)', 1);
  await until(timed.sessionId, result => result.status === 'timed_out');
  assert.equal(call('host.launch', { executable: path.join(root, 'missing.exe') }).ok, false);
  assert.equal(call('host.stop', { sessionId: '../other' }).ok, false);
  assert.equal(call('host.launch', { executable: process.execPath, arguments: 'not an array' }).ok, false);
  assert.equal(ok('host.sessions').sessions.length, 4);
  const gate = spawnSync(python, ['-c',
    'import json,sys\nfrom pathlib import Path\nfrom grant_agent.neyvia_agent import NeyviaToolGateway\nr=Path(sys.argv[1]);args={"executable":sys.argv[2],"arguments":["-e","console.log(123)"]}\ng=NeyviaToolGateway(r,allow_mutations=True,action_scope="host-proof",allowed_mutation_tools={"host.launch"})\na=g.call_native("host.launch",args,action_id="one-launch")\nb=g.call_native("host.launch",args,action_id="one-launch")\nprint(json.dumps({"first":a,"second":b,"readOnly":NeyviaToolGateway(r).call_native("host.launch",args),"noGrant":NeyviaToolGateway(r,allow_mutations=True,allowed_mutation_tools=set()).call_native("host.launch",args,action_id="denied")}))', root, process.execPath],
    { encoding: 'utf8', timeout: 30000, env: { ...process.env, PYTHONPATH: path.resolve('src') } });
  assert.equal(gate.status, 0, gate.stderr);
  const authority = JSON.parse(gate.stdout);
  assert.equal(authority.readOnly.status, 'approval_required');
  assert.equal(authority.noGrant.status, 'mutation_outside_contract');
  assert.equal(authority.first.ok, true);
  assert.equal(authority.second.duplicateSuppressed, true);
  const replaySession = authority.first.toolResult.session.sessionId;
  launched.push(replaySession);
  assert.equal(authority.second.toolResult.session.sessionId, replaySession);
  await until(replaySession, result => result.status === 'completed');
  assert.equal(ok('host.sessions').sessions.length, 5, 'replay must not launch another process');
  writeFileSync(path.join(root,'existing-script.py'),'print("existing script proof")\n');
  const prepared=ok('host.prepare_file',{path:'existing-script.py'});
  assert.equal(prepared.installationRequired,false);
  assert.equal(prepared.dependenciesVerified,false);
  const script=ok('host.launch_file',{path:'existing-script.py',timeoutSeconds:10});
  launched.push(script.sessionId);
  const scriptResult=await until(script.sessionId,result=>result.status==='completed');
  assert(scriptResult.stdout.includes('existing script proof'));
  assert.equal(scriptResult.sourceRecipe.executable,prepared.executable);
  assert.equal(call('host.prepare_file',{path:'../outside.py'}).ok,false);
  assert(!existsSync(path.join(root, 'node_modules')));
  console.log('PASS: installed executable reuse, separate work folders, artifact and output, stop, timeout, failure, input validation; no installation');
} finally {
  let safe = true;
  for (const sessionId of launched) {
    try { ok('host.stop', { sessionId }); await until(sessionId, row => ['completed','failed','stopped','timed_out'].includes(row.status)); }
    catch { safe = false; }
  }
  if (safe) rmSync(root, { recursive: true, force: true });
  else console.error(`Preserved uncertain session evidence: ${root}`);
}
