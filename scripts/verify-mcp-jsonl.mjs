#!/usr/bin/env node
// End-to-end check: Neyvia's stdio client against a disposable newline MCP server.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const script = fileURLToPath(import.meta.url);
if (process.argv[2] === '--server') {
  let pending = '';
  for await (const chunk of process.stdin) {
    pending += chunk.toString('utf8');
    while (pending.includes('\n')) {
      const i = pending.indexOf('\n');
      const line = pending.slice(0, i).trim();
      pending = pending.slice(i + 1);
      if (!line) continue;
      const req = JSON.parse(line);
      const { id, method, params = {} } = req;
      if (method === 'notifications/initialized') continue;
      if (method === 'initialize') send({ jsonrpc: '2.0', id, result: { protocolVersion: '2025-03-26', capabilities: { tools: {} }, serverInfo: { name: 'jsonl-fixture', version: '1' } } });
      else if (method === 'tools/list') send({ jsonrpc: '2.0', id, result: { tools: [{ name: 'ping', description: 'Ping', inputSchema: { type: 'object', properties: {} }, annotations: { readOnlyHint: true } }] } });
      else if (method === 'tools/call') {
        if (params.name === 'slow') await new Promise(resolve => setTimeout(resolve, 600));
        send({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text: 'pong' }], structuredContent: { pong: true }, isError: false } });
      } else send({ jsonrpc: '2.0', id, error: { code: -32601, message: 'unknown method' } });
    }
  }
  function send(value) { process.stdout.write(`${JSON.stringify(value)}\n`); }
} else {
  const repo = path.resolve(path.dirname(script), '..');
  const py = String.raw`
import json, os, sys
sys.path.insert(0, os.path.join(${JSON.stringify(repo)}, 'src'))
from grant_agent.mcp_broker import StdioJsonRpcTransport
t = StdioJsonRpcTransport([${JSON.stringify(process.execPath)}, ${JSON.stringify(script)}, '--server'], request_timeout_s=1, framing='newline')
try:
    tools = t.list_tools()
    assert tools and tools[0]['name'] == 'ping', tools
    result = t.call_tool('ping', {})
    assert result['structuredContent']['pong'] is True, result
    try:
        t._request('unknown')
        raise AssertionError('expected JSON-RPC error')
    except RuntimeError as e:
        assert 'unknown method' in str(e), str(e)
    t.request_timeout_s = 0.15
    try:
        t.call_tool('slow', {})
        raise AssertionError('expected timeout')
    except TimeoutError:
        pass
    child = t._proc
finally:
    t.close()
assert child is None or child.poll() is not None, 'child process was not reaped'
print('jsonl MCP initialize/list/call/error/timeout/close: OK')
`;
  const run = spawnSync(process.env.PYTHON || 'python', ['-c', py], { cwd: repo, encoding: 'utf8', timeout: 15000 });
  assert.equal(run.status, 0, run.stderr || run.stdout || `python exit ${run.status}`);
  process.stdout.write(run.stdout);
}
