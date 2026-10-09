import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { resolveNeyviaPython } from './resolve-neyvia-python.mjs';
import { createHash } from 'node:crypto';

// Exercise the production MCP launch contract from a non-repository workspace.
// No model calls, provider credentials, or network access are needed.
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
process.env.PYTHONPATH = path.join(repo, 'src');
const python = resolveNeyviaPython(repo).python;
const fixture = mkdtempSync(path.join(tmpdir(), 'neyvia-orchestration-'));
try {
  writeFileSync(path.join(fixture, 'input.txt'), 'isolated workspace evidence');
  const config = spawnSync(python, ['-c', 'import json,sys; from pathlib import Path; from grant_agent.neyvia_agent import _codex_neyvia_mcp_args; print(json.dumps(_codex_neyvia_mcp_args(Path(sys.argv[1]),read_only=True)))', fixture], { cwd: repo, encoding: 'utf8', timeout: 60000 });
  assert.equal(config.status, 0, config.stderr || config.error?.message);
  const args = JSON.parse(config.stdout);
  const value = key => args.find(arg => arg.startsWith(key + '='))?.slice(key.length + 1);
  assert.equal(value('features.code_mode_host'), 'true');
  assert.equal(value('features.shell_tool'), 'true');
  const source = JSON.parse(value('mcp_servers.neyvia.env.PYTHONPATH'));
  assert.equal(path.resolve(source), path.join(repo, 'src'));
  const requests = [
    { jsonrpc: '2.0', id: 1, method: 'tools/list' },
    { jsonrpc: '2.0', id: 2, method: 'tools/call', params: { name: 'neyvia.native.call', arguments: { toolId: 'workspace.read', arguments: {path: 'input.txt'} } } },
    { jsonrpc: '2.0', id: 3, method: 'tools/call', params: { name: 'neyvia.native.call', arguments: { toolId: 'skill.live.iterate', arguments: {path: 'input.txt', content: 'forbidden', sessionId: 'verification'} } } },
    { jsonrpc: '2.0', id: 4, method: 'tools/call', params: { name: 'neyvia.tools.search', arguments: {query: 'workspace.read'} } },
    { jsonrpc: '2.0', id: 5, method: 'tools/call', params: { name: 'neyvia.tools.describe', arguments: {name: 'workspace.read'} } },
    { jsonrpc: '2.0', id: 6, method: 'tools/call', params: { name: 'neyvia.tools.search', arguments: {query: 'workspace',limit: 4} } },
    { jsonrpc: '2.0', id: 7, method: 'tools/call', params: { name: 'neyvia.tools.search', arguments: {query: 'skill.live.iterate'} } },
    { jsonrpc: '2.0', id: 8, method: 'tools/call', params: { name: 'neyvia.tools.search', arguments: {query: 'preview.screenshot'} } },
  ];
  const result = spawnSync(JSON.parse(value('mcp_servers.neyvia.command')), JSON.parse(value('mcp_servers.neyvia.args')), {
    cwd: fixture, env: {...process.env, PYTHONPATH: source}, input: requests.map(r => JSON.stringify(r)).join('\n') + '\n', encoding: 'utf8', timeout: 60000,
  });
  assert.equal(result.status, 0, result.stderr || result.error?.message);
  const rows = result.stdout.trim().split(/\r?\n/).map(line => JSON.parse(line));
  assert.equal(rows[0].result.tools.find(t => t.name === 'neyvia.native.call').annotations.readOnlyHint, false, 'The gateway can save scoped task records; it must not claim every call is read-only');
  assert.equal(rows[1].result.structuredContent.result.content, 'isolated workspace evidence');
  const denied = rows[2].result?.structuredContent;
  assert.equal(denied?.ok, false, 'Read-only server must reject mutation');
  assert.equal(denied.status, 'approval_required');
  assert.match(denied.message, /read.only/i);
  assert.equal(readFileSync(path.join(fixture, 'input.txt'), 'utf8'), 'isolated workspace evidence');
  const exact = rows[3].result.structuredContent;
  assert.equal(exact.tools.length, 1);
  assert.equal(exact.tools[0].callTarget, 'neyvia.native.call');
  assert.equal(exact.tools[0].callArguments.toolId, 'workspace.read');
  assert.ok(exact.tools[0].inputSchema.properties.path);
  assert.equal(exact.tools[0].allowedInRun, true);
  assert.equal(exact.tools[0].actionIdRequired, false);
  assert.ok(JSON.stringify(exact).length < 4000, 'An exact native lookup should not emit a compiler catalog');
  assert.deepEqual(rows[4].result.structuredContent.inputSchema, exact.tools[0].inputSchema);
  assert.ok(rows[5].result.structuredContent.tools.length <= 4);
  assert.equal(rows[6].result.structuredContent.tools[0].allowedInRun, false);
  assert.equal(rows[6].result.structuredContent.tools[0].actionIdRequired, true);
  assert.equal(rows[7].result.structuredContent.tools[0].allowedInRun, true);
  assert.equal(rows[7].result.structuredContent.tools[0].actionIdRequired, false);
  assert.match(rows[7].result.structuredContent.tools[0].capturePolicy, /managed proof artifact/);
  if (process.argv.includes('--with-proof')) {
    const proofRoot = path.join(fixture, 'parent');
    const setup = spawnSync(python, ['-c', 'import json,sys; from grant_agent.crashproof import CrashProofStore; from grant_agent.neyvia_conversations import NeyviaConversationStore; s=CrashProofStore(sys.argv[1]); c=NeyviaConversationStore(sys.argv[1],database_path=s.database_path); print(json.dumps(c.create_conversation(kind="orchestration",title="Proof binding verification")))', proofRoot], {cwd:repo,encoding:'utf8',timeout:60000});
    assert.equal(setup.status, 0, setup.stderr);
    const parentId = JSON.parse(setup.stdout).conversationId;
    writeFileSync(path.join(fixture, 'proof.html'), '<!doctype html><title>Proof binding</title><h1>Actual workspace proof</h1>');
    const proofRequest = {jsonrpc:'2.0',id:4,method:'tools/call',params:{name:'neyvia.workspace.prove',arguments:{operation:'screenshot',url:pathToFileURL(path.join(fixture,'proof.html')).href,conversationId:'runtime-session-is-not-the-parent'}}};
    const captured = spawnSync(JSON.parse(value('mcp_servers.neyvia.command')), JSON.parse(value('mcp_servers.neyvia.args')), {cwd:fixture,env:{...process.env,PYTHONPATH:source,NEYVIA_PROOF_ROOT:proofRoot,NEYVIA_PROOF_CONVERSATION_ID:parentId},input:JSON.stringify(proofRequest)+'\n',encoding:'utf8',timeout:60000});
    assert.equal(captured.status, 0, captured.stderr);
    const proof = JSON.parse(captured.stdout).result?.structuredContent;
    assert.equal(proof?.ok, true, proof?.receipt?.receiptPath ? readFileSync(proof.receipt.receiptPath, 'utf8') : captured.stdout);
    assert.equal(proof.attachment.status, 'attached');
    assert.equal(proof.attachment.conversationId, parentId);
    assert.ok(proof.receipt.artifacts.length > 0);
  }
  const evidence = 'isolated launch, file read, mutation denial, tool metadata';
  console.log(JSON.stringify({status:'verified', evidence, sha256:createHash('sha256').update(evidence).digest('hex')}));
} finally {
  rmSync(fixture, {recursive: true, force: true});
}
