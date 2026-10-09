import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdtempSync, readFileSync, existsSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = resolveNeyviaPython(repo).python;
const root = mkdtempSync(path.join(tmpdir(), 'neyvia-workspace-write-'));
const sha256 = value => createHash('sha256').update(value).digest('hex');
function call(toolId, args, actionId, readOnly = false) {
  const command = ['-m', 'grant_agent.neyvia_mcp_stdio', '--root', root, '--session-id', 'artifact-proof'];
  command.push(...(readOnly ? ['--read-only'] : ['--native-mutation-tool', 'workspace.write']));
  const request = {jsonrpc:'2.0', id:1, method:'tools/call', params:{name:'neyvia.native.call', arguments:{toolId, arguments:args, actionId}}};
  const run = spawnSync(python, command, {cwd:repo, env:{...process.env, PYTHONPATH:path.join(repo,'src')},
    encoding:'utf8', input:JSON.stringify(request)+'\n', timeout:60000});
  assert.equal(run.status, 0, run.stderr || run.stdout);
  const response = JSON.parse(run.stdout.trim().split(/\r?\n/).at(-1));
  return response.error ? {ok:false, error:response.error} : response.result.structuredContent;
}
try {
  const file = 'artifacts/site/showcase.html';
  const target = path.join(root, file);
  const body = '<!doctype html><meta charset=utf-8><title>Proof 🌙</title><main>artifact</main>';
  const args = {path:file, content:body};
  const created = call('workspace.write', args, 'artifact-create');
  assert.equal(created.ok, true, JSON.stringify(created));
  assert.equal(created.operationStatus, 'verified');
  assert.equal(created.toolResult.sha256, sha256(body));
  assert.equal(created.toolResult.readbackVerified, true);
  assert.deepEqual(created.filesChanged, [file]);
  assert.equal(readFileSync(target,'utf8'), body);
  const replay = call('workspace.write', args, 'artifact-create');
  assert.equal(replay.duplicateSuppressed, true);
  const readback = call('workspace.read', {path:file}, '', true);
  assert.equal(readback.result.sha256, sha256(body));
  const prefix = call('workspace.read', {path:file, maxChars:17}, '', true).result;
  const suffix = call('workspace.read', {path:file, offset:prefix.nextOffset}, '', true).result;
  assert.equal(prefix.content + suffix.content, body);
  assert.equal(prefix.truncated, true);
  assert.equal(suffix.nextOffset, null);
  assert.equal(suffix.sha256, prefix.sha256);
  assert.equal(call('workspace.read', {path:file, offset:10000}, '', true).result.content, '');
  assert.equal(call('workspace.write',args,'overwrite-denied').ok, false);
  assert.equal(call('workspace.write',{...args,expectedSha256:'0'.repeat(64)},'stale-denied').ok, false);
  assert.equal(readFileSync(target,'utf8'),body);
  const updated = call('workspace.write',{...args,content:body+'\n<!-- updated -->',expectedSha256:sha256(body)},'artifact-update');
  assert.equal(updated.operationStatus,'verified');
  assert.equal(readFileSync(target,'utf8'),body+'\n<!-- updated -->');
  const outside=path.join(path.dirname(root),path.basename(root)+'-escape.txt');
  assert.equal(call('workspace.write',{path:outside,content:'no'},'outside-denied').ok,false);
  assert.equal(existsSync(outside),false);
  const denied = call('workspace.write',{path:'readonly.txt',content:'no'},'readonly-denied',true);
  assert.equal(denied.ok,false);
  assert.equal(existsSync(path.join(root,'readonly.txt')),false);
  const invalid = call('workspace.write',{path:'missing-content.txt'},'invalid-denied');
  assert.equal(invalid.ok,false);
  assert.match(invalid.failure.message,/content/i, 'The original validation error must reach the model');
  assert.equal(existsSync(path.join(root,'missing-content.txt')),false);
  console.log(JSON.stringify({passed:true,route:'actual stdio MCP',createReadback:true,modelReceivesHash:true,replaySuppressed:true,
    expectedHashUpdate:true,overwriteDenied:true,staleHashDenied:true,outsideWorkspaceDenied:true,readonlyDenied:true,validationErrorPreserved:true}));
} finally {
  assert(root.startsWith(path.join(tmpdir(),'neyvia-workspace-write-')));
  rmSync(root,{recursive:true,force:true});
}
