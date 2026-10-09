#!/usr/bin/env node
// Real local HTTP/stdio protocol journey; ports belong exclusively to fixwave.
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const script = fileURLToPath(import.meta.url);
const repo = path.resolve(path.dirname(script), '..');
const tool = name => ({ name, description: name, inputSchema: { type: 'object', properties: {} }, annotations: { readOnlyHint: name !== 'write' } });
const rpc = (id, result) => ({ jsonrpc: '2.0', id, result });
const notice = (method, params = {}) => ({ jsonrpc: '2.0', method, params });

if (process.argv[2] === '--stdio') {
  let pending = '';
  const send = value => process.stdout.write(JSON.stringify(value) + '\n');
  for await (const chunk of process.stdin) {
    pending += chunk.toString('utf8');
    while (pending.includes('\n')) {
      const end = pending.indexOf('\n');
      const { id, method, params = {} } = JSON.parse(pending.slice(0, end));
      pending = pending.slice(end + 1);
      if (method === 'initialize') send(rpc(id, { protocolVersion: '2024-11-05' }));
      else if (method === 'notifications/initialized') setTimeout(() => send(notice('notifications/ready')), 80);
      else if (method === 'tools/list') {
        send(notice('notifications/progress', { progress: 1 }));
        send(rpc(id, params.cursor ? { tools: [tool('second')] } : { tools: [tool('first')], nextCursor: 'page-two' }));
      } else if (method === 'tools/call') send(rpc(id, { content: [{ type: 'text', text: 'real stdio call' }], isError: false }));
    }
  }
} else {
  const wire = [];
  const sessions = new Map();
  const streams = new Map();
  const generations = new Map();
  let nextSession = 0;
  const servers = [];
  for (const port of [47962, 47963]) {
    const server = http.createServer(async (req, res) => {
      const session = req.headers['mcp-session-id'];
      if (req.method !== 'POST') {
        wire.push({ port, method: req.method, session: session || null });
        if (!sessions.has(session)) { res.writeHead(404); res.end(); return; }
        if (req.method === 'DELETE') {
          streams.get(session)?.end(); streams.delete(session); sessions.delete(session);
          res.writeHead(200); res.end(); return;
        }
        if (req.url === '/no-get') { res.writeHead(405); res.end(); return; }
        res.writeHead(200, { 'Content-Type': 'text/event-stream' });
        res.flushHeaders(); streams.set(session, res);
        res.write(`data: ${JSON.stringify(notice('notifications/ready'))}\n\n`);
        const heart = setInterval(() => res.write(': heartbeat\n\n'), 200);
        res.on('close', () => clearInterval(heart));
        return;
      }
      let body = '';
      for await (const chunk of req) body += chunk;
      const msg = JSON.parse(body);
      wire.push({ port, method: msg.method || 'response', session: session || null, params: msg.params || {} });
      assert.match(req.headers.accept || '', /application\/json/);
      assert.match(req.headers.accept || '', /text\/event-stream/);
      if (msg.method === 'initialize') {
        assert.equal(session, undefined);
        const created = `local-${++nextSession}`;
        sessions.set(created, port); generations.set(created, 0);
        res.writeHead(200, { 'Content-Type': 'application/json', 'Mcp-Session-Id': created });
        res.end(JSON.stringify(rpc(msg.id, { protocolVersion: '2025-03-26', capabilities: { tools: { listChanged: true } }, serverInfo: { name: 'local-real-protocol-fixture', version: '1' } })));
        return;
      }
      if (!sessions.has(session)) { res.writeHead(404); res.end(); return; }
      assert.equal(req.headers['mcp-protocol-version'], '2025-03-26');
      if (!('id' in msg)) { res.writeHead(202); res.end(); return; }
      let answer;
      let events = [notice('notifications/progress', { progress: 1, total: 2 })];
      if (msg.method === 'tools/list') {
        const generation = generations.get(session);
        answer = rpc(msg.id, msg.params.cursor ? { tools: [tool(generation ? 'new-third' : 'third'), tool('write')] } : { tools: [tool('ping'), tool('emit')], nextCursor: 'last-page' });
      } else if (msg.method === 'tools/call') {
        if (msg.params.name === 'error') answer = { jsonrpc: '2.0', id: msg.id, error: { code: -32603, message: 'deliberate protocol error' } };
      else {
          if (msg.params.name === 'stall') {
            res.writeHead(200, { 'Content-Type': 'text/event-stream' });
            res.flushHeaders();
            const heart = setInterval(() => res.write(': still waiting\n\n'), 20);
            res.on('close', () => clearInterval(heart));
            return;
          }
          answer = rpc(msg.id, { content: [{ type: 'text', text: `port ${port}: actual HTTP call` }], structuredContent: { received: msg.params.arguments, port }, isError: false });
          if (msg.params.name === 'emit') {
            generations.set(session, generations.get(session) + 1);
            setTimeout(() => {
              const stream = streams.get(session);
              if (stream) for (const method of ['notifications/tools/list_changed', 'notifications/resources/list_changed', 'notifications/resources/updated']) stream.write(`data: ${JSON.stringify(notice(method, { uri: 'local://real-resource' }))}\n\n`);
            }, 80);
          }
          if (msg.params.name === 'expire') {
            setTimeout(() => { sessions.delete(session); streams.get(session)?.end(); streams.delete(session); }, 40);
          }
        }
      } else if (msg.method === 'cursor-cycle') answer = rpc(msg.id, { tools: [], nextCursor: 'same' });
      else answer = { jsonrpc: '2.0', id: msg.id, error: { code: -32601, message: 'unknown method' } };
      if (port === 47962) {
        res.writeHead(200, { 'Content-Type': 'text/event-stream' });
        // Split data across network writes and support multiline SSE JSON fields.
        for (const event of [...events, answer]) {
          const data = JSON.stringify(event);
          const split = data.indexOf(',');
          res.write(`event: message\ndata: ${data.slice(0, split + 1)}\n`);
          res.write(`data: ${data.slice(split + 1)}\n\n`);
        }
        res.end();
      } else {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(answer));
      }
    });
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', resolve); });
    servers.push(server);
  }
  const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'fixwave-mcp-'));
  const py = String.raw`
import json, os, sys, time
sys.path.insert(0, os.path.join(${JSON.stringify(repo)}, 'src'))
from grant_agent.mcp_broker import McpOutboundBroker, StdioJsonRpcTransport, register_with_progressive_surface
from grant_agent.mcp_protocol import JsonRpcFrameDecoder, list_all_tools
from grant_agent.mcp_http_transport import StreamableHttpTransport
from grant_agent.codex_plugin_access import CodexPluginAccess
from pathlib import Path
from grant_agent.progressive_tools import ProgressiveToolSurface
b = McpOutboundBroker(${JSON.stringify(scratch)}, config={'servers': {
    'sse': {'url': 'http://127.0.0.1:47962/mcp'},
    'json': {'transport': 'http', 'url': 'http://127.0.0.1:47963/mcp'}
}}, include_default_demo=False)
proof = {}
try:
    surface = ProgressiveToolSurface()
    register_with_progressive_surface(surface, b)
    for server in ['sse', 'json']:
        discovered = surface.call('mcp.search', {'server': server, 'limit': 20})['tools']
        assert {row['name'] for row in discovered} == {'ping', 'emit', 'third', 'write'}, discovered
        assert not any('inputSchema' in row for row in discovered)
        real = surface.call('mcp.call', {'server': server, 'tool': 'ping', 'arguments': {}, 'missionId': 'fixwave-item4'})
        assert real['ok'], real
        blocked = surface.call('mcp.call', {'server': server, 'tool': 'write', 'arguments': {}})
        assert blocked['status'] == 'approval_required', blocked
        transport = b.get_server(server)._transport_impl
        session = transport.session_id
        emitted = b.call(server, 'emit', {})
        assert emitted['ok'], emitted
        deadline = time.monotonic() + 4
        while b.get_server(server).resource_revision != 2 and time.monotonic() < deadline:
            time.sleep(.02)
        state = b.get_server(server)
        assert state.resource_revision == 2 and state.catalog_revision == 1, state.compact()
        assert state.readiness == 'ready', state.compact()
        changed = surface.call('mcp.search', {'server': server, 'limit': 20})['tools']
        assert 'new-third' in {row['name'] for row in changed} and 'third' not in {row['name'] for row in changed}, changed
        observed = surface.call('mcp.servers', {})
        assert any(e['method'] == 'notifications/tools/list_changed' for e in observed['incomingNotifications']), observed
        if server == 'sse':
            assert any(e['method'] == 'notifications/progress' for e in observed['incomingNotifications']), observed
        try:
            transport.call_tool('error', {})
            raise AssertionError('JSON-RPC error must propagate')
        except RuntimeError as error:
            assert 'deliberate protocol error' in str(error)
        transport.request_timeout_s = .15
        try:
            transport.call_tool('stall', {})
            raise AssertionError('SSE heartbeat stream must respect deadline')
        except TimeoutError:
            pass
        finally:
            transport.request_timeout_s = 30
        transport.call_tool('expire', {})
        time.sleep(.12)
        recovered = transport.call_tool('ping', {})
        assert recovered['structuredContent']['port'] in [47962,47963]
        assert transport.session_id != session, 'session was not renewed'
        proof[server] = {'initialToolCount': len(discovered), 'realCall': real['status'], 'mutationBlocked': blocked['status'], 'notificationCount': state.notification_count, 'catalogRefreshed': True, 'resourcesUpdated': state.resource_revision, 'readiness': state.readiness, 'sessionRenewed': True, 'errorPropagated': True, 'heartbeatStreamDeadline': True}
    # Silent parser and pagination invariants, exercised through the production helpers.
    try:
        list_all_tools(lambda *args: {'tools': [], 'nextCursor': 'cycle'})
        raise AssertionError('cursor cycle must fail')
    except RuntimeError as e:
        assert 'cursor' in str(e)
    unicode = json.dumps({'jsonrpc': '2.0', 'id': 42, 'result': 'été'}, ensure_ascii=False).encode('utf-8')
    decoder = JsonRpcFrameDecoder('content_length')
    wire = ('Content-Length: %s\r\n\r\n' % len(unicode)).encode() + unicode
    frames = []
    for byte in wire: frames += decoder.feed(bytes([byte]))
    assert frames == [{'jsonrpc':'2.0','id':42,'result':'été'}], frames
    proof['silentInvariants'] = ['repeated pagination cursor rejects', 'bytewise Unicode content-length framing']
    plain = StreamableHttpTransport('http://127.0.0.1:47963/no-get')
    try:
        assert len(plain.list_tools()) == 4
        assert plain.call_tool('ping', {})['structuredContent']['port'] == 47963
        proof['optionalGet405'] = True
    finally:
        plain.close()
    config_home = Path(${JSON.stringify(scratch)}) / 'codex-scratch'
    config_home.mkdir()
    (config_home / 'config.toml').write_text('''[mcp_servers.local]
url = "http://127.0.0.1:47963/mcp"
[mcp_servers.local.http_headers]
X-Local-Fixture = "non-secret-marker"
[mcp_servers.oauth_only]
url = "http://127.0.0.1:47963/mcp"
bearer_token_env_var = "DO_NOT_READ_TEST_TOKEN"
''', encoding='utf-8')
    imported = CodexPluginAccess(Path(${JSON.stringify(scratch)}), config_home)
    try:
        assert imported.inventory()['nativeServerCount'] == 1, imported.inventory()
        assert any(row['status'] == 'adapter_required' for row in imported.inventory()['servers'])
        target = next(iter(imported.configs))
        assert len(imported.search(target)['tools']) == 4
        real = imported.call(target, 'ping', {}, approved=True)
        assert real['ok'], real
        proof['codexImport'] = {'plainUrlCalls': True, 'oauthStillAdapterRequired': True, 'config': 'disposable local TOML only'}
    finally:
        imported.broker.close()
finally:
    b.close()
t = StdioJsonRpcTransport([${JSON.stringify(process.execPath)}, ${JSON.stringify(script)}, '--stdio'], framing='newline', request_timeout_s=2)
try:
    assert [row['name'] for row in t.list_tools()] == ['first', 'second']
    assert not t.call_tool('first', {})['isError']
    time.sleep(.2)
    events = t.notifications.drain()
    assert any(e['method'] == 'notifications/ready' for e in events), events
    assert any(e['method'] == 'notifications/progress' for e in events), events
    proof['stdio'] = {'pagesComplete':True,'callCompleted':True,'idleReadinessNotification':True,'progressNotification':True}
finally:
    t.close()
print(json.dumps(proof))
`;
  try {
    const child = spawn(process.env.PYTHON || String.raw`C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe`, ['-c', py], { cwd: repo, windowsHide: true });
    let stdout = '', stderr = '';
    child.stdout.on('data', data => stdout += data);
    child.stderr.on('data', data => stderr += data);
    const code = await new Promise(resolve => child.on('close', resolve));
    assert.equal(code, 0, stderr || stdout);
    const result = JSON.parse(stdout.trim());
    for (const port of [47962, 47963]) {
      const calls = wire.filter(row => row.port === port);
      assert.ok(calls.some(row => row.method === 'tools/list' && row.params.cursor === 'last-page'));
      assert.ok(calls.filter(row => row.method === 'initialize').length >= 2);
      assert.ok(calls.some(row => row.method === 'DELETE'));
      assert.ok(!calls.some(row => row.method === 'tools/call' && row.params.name === 'write'));
    }
    const evidence = { item: 4, generatedAt: new Date().toISOString(), command: 'node scripts/verify-fixwave-mcp.mjs', boundary: 'Actual disposable MCP HTTP servers on 47962/47963 and a real stdio subprocess; broker progressive tools called in process', result, wire, missing: ['Legacy 2024 SSE endpoint transport remains explicitly unsupported', 'No OAuth login flow added', 'SSE event-ID replay/resume is not implemented; GET reconnects without replay'] };
    fs.mkdirSync(path.join(repo, 'scripts/evidence'), { recursive: true });
    fs.writeFileSync(path.join(repo, 'scripts/evidence/fixwave-item4.json'), JSON.stringify(evidence, null, 2) + '\n');
    console.log(JSON.stringify(result, null, 2));
  } finally {
    for (const stream of streams.values()) stream.end();
    for (const server of servers) await new Promise(resolve => server.close(resolve));
    fs.rmSync(scratch, { recursive: true, force: true });
  }
}
