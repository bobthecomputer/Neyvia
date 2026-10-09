/* Real HTTP/tool/desktop journeys in an owned, restartable backend. No pytest. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const zlib = require('node:zlib');
const assert = require('node:assert/strict');
const { spawn, spawnSync } = require('node:child_process');
const repo = path.resolve(__dirname, '..');
const python = 'C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe';
const work = path.join(repo, '.agent_control/T8');
const root = path.join(work, 'proof-' + Date.now());
const base = 'http://127.0.0.1:48221';
const receiptPath = path.join(repo, 'scripts/evidence/T8.json');
const env = { ...process.env, PYTHONPATH: path.join(repo, 'src'),
  NEYVIA_UI_STATE_ROOT: root, NEYVIA_CONNECTED_SERVICE_PORT: '48221',
  NEYVIA_COORDINATOR_AUTOSTART: '0', FLUXIO_WATCHDOG_AUTOSTART: '0', NEYVIA_TOOL_AUTO_UPDATE: '0' };
const receipt = { track: 'T8', startedAt: new Date().toISOString(), port: 48221, root,
  boundary: 'Real authenticated backend HTTP, native registry, manual and desktop bridge. UI rendered gestures/classic migration are not proven.',
  checks: [], journeys: [], missing: ['Claude UI: Outputs panel, dock-to-float drag and complete classic-screen migration', 'Rendered browser proof: CUA inventory has no browsers/apps', 'Installed Tauri/WebView journey', 'NAS snapshot: excluded by explicit isolation/port restrictions'] };
let server, cookie = '';
const digest = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
function pixelPng() {
  const chunk = (type, data) => {
    const body = Buffer.concat([Buffer.from(type), data]);
    let crc = 0xffffffff;
    for (const byte of body) {
      crc ^= byte;
      for (let bit = 0; bit < 8; bit++) crc = crc & 1 ? (crc >>> 1) ^ 0xedb88320 : crc >>> 1;
    }
    const size = Buffer.alloc(4), checksum = Buffer.alloc(4);
    size.writeUInt32BE(data.length); checksum.writeUInt32BE((crc ^ 0xffffffff) >>> 0);
    return Buffer.concat([size, body, checksum]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(1, 0); header.writeUInt32BE(1, 4); header[8] = 8; header[9] = 6;
  return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]), chunk('IHDR', header),
    chunk('IDAT', zlib.deflateSync(Buffer.from([0,64,130,80,255]))), chunk('IEND', Buffer.alloc(0))]);
}
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
function save() {
  receipt.completedAt = new Date().toISOString();
  receipt.passed = receipt.checks.filter(row => row.ok).length;
  receipt.failed = receipt.checks.filter(row => !row.ok).length;
  const modelReceipt = path.join(repo, 'scripts/evidence/T8-luna.json');
  if (fs.existsSync(modelReceipt)) receipt.smallModel = JSON.parse(fs.readFileSync(modelReceipt));
  receipt.registrations = { commands: ['artifact_publish_command', 'artifact_list_command', 'artifact_get_command', 'artifact_open_command', 'app_open_command'],
    tools: ['neyvia.artifact.publish', 'neyvia.artifact.list', 'neyvia.artifact.get', 'neyvia.artifact.open', 'neyvia.app.open'],
    http: ['GET/POST /api/ui/outputs', 'POST /api/ui/navigation', 'POST /api/backend', 'POST /api/ui/tools/call'],
    dispatch: 'web_backend.py -> neyvia_outputs.handle_command -> shared workspace bus',
    desktop: 'desktop_bridge ALLOWED_DESKTOP_COMMANDS -> authenticated persistent service; existing generic Tauri call_desktop_backend_command forwards the command envelope',
    mcp: 'plugins/neyvia/mcp/neyvia_mcp.py PORTED and gateway; no global CLI config changed',
    manual: 'config/neyvia_manuals.json -> manuals/outputs.manual.json publish-and-open',
    producers: ['neyvia_panes.write_file', 'neyvia_image_tools edits/generation/export; other producers explicitly call artifact.publish'] };
  receipt.repositoryManualCheck = { command: 'Python313 scripts/build_grounded_manuals.py --check', ok: false,
    blocker: 'Existing manuals/design.manual.json workspace.read schema differs from live tool; new outputs manual validates and executes independently' };
  receipt.sourceHashes = Object.fromEntries(['src/grant_agent/neyvia_outputs.py', 'src/grant_agent/neyvia_voice.py',
    'src/grant_agent/neyvia_workspace_tools.py', 'src/grant_agent/neyvia_ui_api.py', 'src/grant_agent/web_backend.py',
    'src/grant_agent/desktop_bridge.py', 'src/grant_agent/neyvia_panes.py', 'src/grant_agent/neyvia_image_tools.py',
    'manuals/outputs.manual.json', 'config/neyvia_manuals.json', 'plugins/neyvia/mcp/neyvia_mcp.py', 'scripts/verify_T8.cjs'].map(file => [file, digest(path.join(repo, file))]));
  fs.mkdirSync(path.dirname(receiptPath), { recursive: true });
  fs.writeFileSync(receiptPath, JSON.stringify(receipt, null, 2) + '\n');
}
async function check(name, action) {
  const start = Date.now();
  try { await action(); receipt.checks.push({ name, ok: true, ms: Date.now() - start }); console.log('PASS ' + name); }
  catch (error) { receipt.checks.push({ name, ok: false, error: error.message }); save(); throw error; }
}
async function request(route, body, auth = true) {
  const start = Date.now();
  const response = await fetch(base + route, { method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json', ...(auth && cookie ? { Cookie: cookie } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: AbortSignal.timeout(60000) });
  const data = await response.json();
  const safeBody = body === undefined ? undefined : JSON.parse(JSON.stringify(body, (key, value) => /password/i.test(key) ? '[masked]' : value));
  receipt.journeys.push({ route, body: safeBody, status: response.status, ms: Date.now() - start, response: data });
  return { status: response.status, body: data, response };
}
async function login() {
  const result = await request('/api/auth/local-session', {}, false);
  assert.equal(result.status, 200);
  cookie = result.response.headers.get('set-cookie').split(';')[0];
}
async function output(op, args) {
  const result = await request('/api/ui/outputs', { op, args });
  assert.equal(result.status, 200, JSON.stringify(result.body));
  assert.equal(result.body.ok, true);
  return result.body.data;
}
function unwrap(row) {
  while (row && row.tool && row.result) { assert.notEqual(row.ok, false, JSON.stringify(row)); row = row.result; }
  assert.notEqual(row?.ok, false, JSON.stringify(row));
  return row;
}
async function tool(name, args) {
  const result = await request('/api/ui/tools/call', { tool: 'neyvia.' + name, arguments: args });
  assert.equal(result.status, 200, JSON.stringify(result.body));
  return unwrap(result.body.data);
}
async function start() {
  // Never take over another process's port.
  try { await fetch(base + '/api/health', { signal: AbortSignal.timeout(1000) }); throw new Error('48221 is already occupied; refusing to touch its owner'); }
  catch (error) { if (error.message.includes('already occupied')) throw error; }
  fs.mkdirSync(root, { recursive: true });
  const log = fs.openSync(path.join(work, 'backend-' + Date.now() + '.log'), 'a');
  server = spawn(python, [path.join(repo, 'scripts/run_web_backend.py'), '--host', '127.0.0.1', '--port', '48221', '--root', root, '--skip-runtime-auto-update'],
    { cwd: repo, env, windowsHide: true, stdio: ['ignore', log, log] });
  fs.closeSync(log);
  for (let i = 0; i < 60; i++) {
    if (server.exitCode !== null) throw new Error('Backend exited: ' + server.exitCode);
    try { const response = await fetch(base + '/api/health', { signal: AbortSignal.timeout(1000) }); if (response.ok && (await response.json()).ok) return; }
    catch {}
    await delay(500);
  }
  throw new Error('Owned backend did not become healthy');
}
async function stop() {
  if (!server || server.exitCode !== null) return;
  const child = server;
  await new Promise(resolve => { child.once('exit', resolve); child.kill(); });
  server = null;
}
function bridge(command, payload, workspace = root) {
  const result = spawnSync(python, ['-m', 'grant_agent.desktop_bridge', '--root', workspace], {
    cwd: repo, env, windowsHide: true, input: JSON.stringify({ command, payload }), encoding: 'utf8', timeout: 65000 });
  assert.equal(result.status, 0, result.stderr);
  const answer = JSON.parse(result.stdout);
  receipt.journeys.push({ desktop: command, payload, response: answer });
  assert.notEqual(answer.ok, false, JSON.stringify(answer));
  return unwrap(answer.data ?? answer);
}
async function main() {
  await start();
  await check('Anonymous list/publish and navigation are rejected', async () => {
    for (const [route, body] of [['/api/ui/outputs', undefined], ['/api/ui/outputs', { op: 'publish', args: { path: 'secret.txt' } }], ['/api/ui/navigation', { app: 'notes' }]])
      assert.equal((await request(route, body, false)).status, 401);
  });
  await login();
  await check('Another authenticated account cannot publish or navigate through either API', async () => {
    const password = crypto.randomBytes(18).toString('hex');
    const created = await request('/api/backend', { command: 'accounts_update_command', payload: { op: 'create', username: 'T8guest', password } });
    assert.equal(created.status, 200, JSON.stringify(created.body));
    const ownerCookie = cookie;
    const signedIn = await request('/api/auth/login', { username: 'T8guest', password }, false);
    assert.equal(signedIn.status, 200, JSON.stringify(signedIn.body));
    cookie = signedIn.response.headers.get('set-cookie').split(';')[0];
    try {
      for (const [route, body] of [['/api/ui/outputs', { op: 'publish', args: { path: 'secret.txt' } }], ['/api/ui/navigation', { app: 'notes' }],
        ['/api/backend', { command: 'artifact_publish_command', payload: { path: 'secret.txt' } }], ['/api/backend', { command: 'app_open_command', payload: { app: 'notes' } }]])
        assert.equal((await request(route, body)).status, 403);
    } finally { cookie = ownerCookie; }
  });
  const file = path.join(root, 'result.txt');
  await check('Real file-editor save automatically publishes bytes', async () => {
    const saved = await request('/api/ui/panes', { op: 'file.write', args: { path: file, text: 'T8 user-path output\n', baseHash: '' } });
    assert.equal(saved.status, 200, JSON.stringify(saved.body));
    assert.equal(saved.body.data.publication.artifact.sha256, digest(file));
  });
  const fixtures = [
    ['file', file, null],
    ['diff', path.join(root, 'change.patch'), '--- a/result.txt\n+++ b/result.txt\n@@ -1 +1 @@\n-T8 user-path output\n+T8 revised output\n'],
    ['image', path.join(root, 'pixel.png'), pixelPng()],
    ['report', path.join(root, 'report.html'), '<!doctype html><title>T8 report</title><h1>Backend publication run</h1><p>Real file saved and hashed.</p>'],
    ['receipt', path.join(root, 'receipt.json'), JSON.stringify({ task: 'T8', operation: 'file.write', sha256: digest(file) })]
  ];
  const published = [];
  for (const [kind, location, content] of fixtures) {
    if (content !== null) fs.writeFileSync(location, content);
    await check('Publish/read/open real ' + kind + ' output through shared state', async () => {
      const result = await output('publish', { path: location, kind, title: 'T8 ' + kind, sessionId: 'T8-session', runId: 'T8-run', requestId: 'T8-' + kind });
      assert.equal(result.artifact.sha256, digest(location));
      assert.equal(result.event.action, 'artifact.published');
      published.push(result.artifact);
      const observed = await tool('artifact.get', { id: result.artifact.id });
      assert.equal(observed.availability, 'available');
      const opened = await output('open', { id: result.artifact.id });
      assert.equal(opened.event.action, 'pane.show');
      assert.equal(opened.event.payload.target, location);
      assert.equal(opened.preview.kind, kind === 'image' ? 'image' : kind === 'report' ? 'html' : 'text');
      if (kind === 'diff') assert.equal(opened.preview.text, content);
      if (kind === 'report') {
        const response = await fetch(base + opened.preview.url);
        assert.equal(response.status, 200);
        assert.match(response.headers.get('content-security-policy'), /sandbox/);
        assert.equal(await response.text(), content);
      }
    });
  }
  await check('Session/run filters and pagination retain every kind', async () => {
    const first = (await request('/api/ui/outputs?sessionId=T8-session&runId=T8-run&limit=2&offset=0')).body.data;
    const rest = await output('list', { sessionId: 'T8-session', runId: 'T8-run', limit: 3, offset: 2 });
    assert.equal(first.total, 5); assert.equal(rest.total, 5);
    assert.equal(new Set([...first.artifacts, ...rest.artifacts].map(row => row.id)).size, 5);
    for (const kind of ['file', 'diff', 'image', 'report', 'receipt']) assert.equal((await output('list', { kind, sessionId: 'T8-session' })).total, 1);
    assert.equal((await output('list', { runId: 'unknown-run' })).total, 0);
  });
  await check('Concurrent identical retries reuse one row and one event', async () => {
    const args = { path: file, kind: 'file', title: 'T8 file', sessionId: 'T8-session', runId: 'T8-run', requestId: 'T8-file' };
    const results = await Promise.all(Array.from({ length: 4 }, () => output('publish', args)));
    assert.ok(results.every(row => row.replayed && row.artifact.id === published[0].id && !row.event));
    assert.equal((await output('list', { sessionId: 'T8-session' })).total, 5);
  });
  await check('Changed request intent refuses without another publication', async () => {
    const result = await request('/api/ui/outputs', { op: 'publish', args: { path: file, requestId: 'T8-file', title: 'Changed' } });
    assert.equal(result.status, 409); assert.equal(result.body.data.status, 'conflict');
  });
  await check('Relative path and no-request deduplication work', async () => {
    const a = await output('publish', { path: 'receipt.json', kind: 'receipt' });
    const b = await output('publish', { path: path.join(root, 'receipt.json'), kind: 'receipt' });
    assert.equal(a.artifact.id, b.artifact.id); assert.equal(b.replayed, true);
  });
  await check('Changed bytes cannot open old publication; new version records lineage', async () => {
    fs.appendFileSync(file, 'Second version\n');
    assert.equal((await output('get', { id: published[0].id })).availability, 'changed');
    assert.equal((await request('/api/ui/outputs', { op: 'open', args: { id: published[0].id } })).status, 409);
    assert.equal((await request('/api/ui/outputs', { op: 'publish', args: { path: file, kind: 'file', title: 'T8 file', sessionId: 'T8-session', runId: 'T8-run', requestId: 'T8-file' } })).status, 409);
    const next = await output('publish', { path: file, kind: 'file', sessionId: 'T8-session', runId: 'T8-run', requestId: 'T8-file-v2' });
    assert.equal(next.artifact.previousId, published[0].id);
  });
  await check('Missing file refuses open; history remains readable', async () => {
    const image = fixtures[2][1]; fs.renameSync(image, image + '.kept');
    assert.equal((await output('get', { id: published[2].id })).availability, 'missing');
    assert.equal((await request('/api/ui/outputs', { op: 'open', args: { id: published[2].id } })).status, 404);
    fs.renameSync(image + '.kept', image);
  });
  await check('Real Image Studio resize automatically publishes its generated PNG', async () => {
    await tool('image.open', { source: fixtures[2][1] });
    const resized = await tool('image.resize', { width: 2, height: 2 });
    assert.equal(resized.publication.artifact.kind, 'image');
    assert.equal(resized.publication.artifact.sha256, digest(resized.publication.artifact.path));
    const preview = await output('open', { id: resized.publication.artifact.id });
    assert.equal(preview.preview.kind, 'image');
  });
  await check('Invalid, absent, oversized metadata and out-of-scope publications refuse', async () => {
    for (const args of [{ path: 'missing.txt' }, { path: 'receipt.json', kind: 'invented' }, { path: 'receipt.json', metadata: { value: 'x'.repeat(17000) } }, { path: 'C:/Windows/win.ini' }]) {
      const result = await request('/api/ui/outputs', { op: 'publish', args });
      assert.ok([400, 404].includes(result.status));
    }
    for (const args of [{ limit: 0 }, { limit: true }, { offset: -1 }]) assert.equal((await request('/api/ui/outputs', { op: 'list', args })).status, 400);
  });
  await check('App navigation uses the existing bus for apps and panes', async () => {
    for (const [app, target, action] of [['notes', file, 'app.open'], ['files', root, 'app.open'], ['outputs', '', 'pane.show'], ['runtime', '', 'pane.show'], ['browser', 'http://127.0.0.1:48221', 'pane.show'], ['settings', 'tidy', 'pane.show']]) {
      const result = await request('/api/ui/navigation', { app, target });
      assert.equal(result.status, 200, JSON.stringify(result.body));
      assert.equal(result.body.data.app, app);
      assert.equal(result.body.data.event.action, action);
      assert.equal(result.body.data.event.payload.target, target);
    }
    assert.equal((await request('/api/ui/navigation', { app: 'invented-app' })).status, 400);
    assert.equal((await request('/api/ui/navigation', { app: 'unity' })).status, 400);
    assert.equal((await request('/api/ui/navigation', { app: 'notes', target: {} })).status, 400);
    assert.equal((await tool('app.open', { app: 'outputs' })).event.payload.kind, 'outputs');
    for (const app of ['agent', 'builder-review', 'notebook', 'lab', 'library', 'phone', 'preview', 'harnesses', 'skills', 'rule-sets', 'image-playground', 'app-factory', 'ios-studio', 'lumaforge', 'frameweave', 'citecraft', 'aegis-range', 'cueledger']) {
      const result = await request('/api/ui/navigation', { app, target: 'T8-target' });
      assert.equal(result.status, 200, JSON.stringify(result.body));
      assert.equal(result.body.data.event.action, 'app.open');
      assert.equal(result.body.data.event.payload.app, app);
      assert.equal(result.body.data.event.payload.target, 'T8-target');
    }
  });
  await check('Grounded manual validates and executes publish/verify/open', async () => {
    const validated = await tool('manual.validate', { id: 'outputs' });
    assert.equal(validated.manuals[0].grounded, true);
    const result = await tool('manual.run', { id: 'outputs', chapter: 'overview', procedure: 'publish-and-open', inputs: { path: fixtures[4][1], kind: 'receipt', requestId: 'T8-manual-receipt' } });
    assert.equal(result.status, 'completed', JSON.stringify(result));
    receipt.manual = result;
  });
  await check('Fresh desktop workers publish/list/open and navigate same persistent service', async () => {
    assert.ok(bridge('artifact_list_command', {}).artifacts.length >= 5);
    const row = bridge('artifact_publish_command', { payload: { path: fixtures[4][1], kind: 'receipt', requestId: 'T8-desktop' } });
    assert.equal(row.artifact.sha256, digest(fixtures[4][1]));
    assert.equal(bridge('artifact_get_command', { id: row.artifact.id }).availability, 'available');
    assert.equal(bridge('artifact_open_command', { id: row.artifact.id }).event.action, 'pane.show');
    assert.equal(bridge('app_open_command', { app: 'outputs' }).event.payload.kind, 'outputs');
    const mismatch = spawnSync(python, ['-m', 'grant_agent.desktop_bridge', '--root', path.join(work, 'wrong-root')], { cwd: repo, env, windowsHide: true, input: JSON.stringify({ command: 'artifact_list_command', payload: {} }), encoding: 'utf8', timeout: 65000 });
    const answer = JSON.parse(mismatch.stdout);
    assert.equal(answer.data?.ok ?? answer.ok, false, JSON.stringify(answer));
    receipt.journeys.push({ desktop: 'wrong-workspace', response: answer });
  });
  const before = await output('list', {});
  await stop(); await start(); await login();
  await check('Backend restart preserves exact registry, request IDs and preview capability', async () => {
    const after = await output('list', {});
    assert.deepEqual(after.artifacts, before.artifacts);
    assert.equal((await output('get', { id: published[4].id })).availability, 'available');
    const replay = await output('publish', { path: fixtures[4][1], kind: 'receipt', title: 'T8 receipt', sessionId: 'T8-session', runId: 'T8-run', requestId: 'T8-receipt' });
    assert.equal(replay.replayed, true); assert.equal(replay.artifact.id, published[4].id);
    assert.equal((await output('open', { id: published[3].id })).preview.kind, 'html');
  });
  receipt.finalOutputs = (await output('list', {})).artifacts;
  receipt.ok = true;
  save();
  console.log(JSON.stringify({ ok: true, passed: receipt.passed, receipt: receiptPath }));
  if (process.argv.includes('--hold')) {
    fs.writeFileSync(path.join(work, 'held-server.json'), JSON.stringify({ pid: server.pid, port: 48221, root, parentPid: process.pid }) + '\n');
    console.log('Holding owned backend for follow-up proof. Stop this verifier to stop it.');
    await new Promise(resolve => { process.once('SIGINT', resolve); process.once('SIGTERM', resolve); });
  }
}
main().catch(error => { receipt.ok = false; receipt.error = error.message; save(); console.error(error.stack); process.exitCode = 1; }).finally(stop);
