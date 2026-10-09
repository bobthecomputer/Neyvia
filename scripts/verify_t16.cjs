// Real native/MCP/HTTP journey. Requires the T16 backend and disposable Notepad.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const base = 'http://127.0.0.1:48171';
const repo = path.resolve(__dirname, '..');
const python = 'C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe';
const evidence = path.join(__dirname, 'evidence');
let cookie = '', proc, monitor, monitorId = 0, monitorPending = new Map(), nextId = 0, pending = new Map();
const checks = [], receipts = {};
function check(name, value) { assert.ok(value, name); checks.push({ name, passed: true }); }
async function http(op, args = {}) {
  const response = await fetch(base + '/api/ui/cua', { method: 'POST', headers: { 'Content-Type': 'application/json', Cookie: cookie }, body: JSON.stringify({ op, args }) });
  const value = await response.json();
  if (!response.ok || !value.ok) throw new Error(`${op}: ${JSON.stringify(value)}`);
  return value.data;
}
async function state() { return (await (await fetch(base + '/api/ui/cua/state', { headers: { Cookie: cookie } })).json()).data; }
async function until(fn, timeout = 15000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { const value = await fn(); if (value) return value; await new Promise(r => setTimeout(r, 100)); }
  throw new Error('Native journey timed out');
}
function rpc(method, params) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`MCP timeout: ${method}`)); }, 140000);
    pending.set(id, { resolve, reject, timer });
    proc.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
  });
}
async function tool(name, arguments = {}, sessionId) { return rpc('tools/call', { name, arguments, ...(sessionId ? { _meta: { 'neyvia/preview': { session: sessionId } } } : {}) }); }
function compact(r) { return { structuredContent: r.structuredContent, isError: Boolean(r.isError), _meta: r._meta }; }
function nativeStatus() {
  if (!monitor) {
    const digest = require('node:crypto').createHash('sha256').update(fs.readFileSync(path.join(repo, 'tools/cua-driver-win/NativeWorker.cs'))).digest('hex');
    const assembly = path.join(repo, 'tools/cua-driver-win/.build', digest + '.dll');
    if (!fs.existsSync(assembly)) throw new Error('Build native worker first: system Python -B -c "from grant_agent.cua_native import NativeWorker; NativeWorker.assembly()"');
    monitor = spawn('powershell.exe', ['-NoLogo', '-NoProfile', '-NonInteractive', '-STA', '-ExecutionPolicy', 'Bypass', '-File', path.join(repo, 'tools/cua-driver-win/driver.ps1'), '-AssemblyPath', assembly], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
    let buffer = '';
    monitor.stdout.setEncoding('utf8');
    monitor.stdout.on('data', chunk => { buffer += chunk; while (buffer.includes('\n')) {
      const at = buffer.indexOf('\n'), row = JSON.parse(buffer.slice(0, at)); buffer = buffer.slice(at + 1);
      const waiter = monitorPending.get(row.id);
      if (waiter) { monitorPending.delete(row.id); clearTimeout(waiter.timer); row.ok ? waiter.resolve(row.data) : waiter.reject(new Error(row.error)); }
    }});
  }
  const id = String(++monitorId);
  return new Promise((resolve, reject) => { const timer = setTimeout(() => reject(new Error('Native monitor timeout')), 10000); monitorPending.set(id, { resolve, reject, timer }); monitor.stdin.write(JSON.stringify({ id, op: 'status', args: {} }) + '\n'); });
}
async function main() {
  receipts.focusBefore = await nativeStatus();
  const anonymous = await fetch(base + '/api/ui/cua/state');
  check('Native preview requires authentication', anonymous.status === 401);
  const login = await fetch(base + '/api/auth/local-session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  cookie = login.headers.getSetCookie().map(s => s.split(';')[0]).join('; ');
  check('Scratch PC local-session login', login.ok && cookie);
  receipts.focusAfterLogin = await nativeStatus();
  const before = await state();
  for (const old of before.sessions.filter(s => s.owner?.chatId === 't16-proof' && s.status !== 'ended' && s.allow.some(a => a.name === 't16nativeprobe'))) {
    await http('end', { sessionId: old.id }); // Only this journey's disposable grants.
  }
  let session = before.sessions.find(s => s.owner?.chatId === 't16-proof' && s.status !== 'ended' && s.allow.some(a => a.name === 'notepad'));
  const recovered = Boolean(session);
  if (!session) session = await http('open', { apps: ['notepad.exe'], chatId: 't16-proof', app: 'codex', title: 'Native background Notepad proof' });
  receipts.recovery = session;
  check('Restart preserved the owner grant and paused execution', !recovered || session.control === 'paul');
  session = await http('control', { sessionId: session.id, mode: 'agent', note: 'T16 proof: continue in the disposable note.' });
  const nativeWindow = session.windows.find(w => w.title.includes('T16-native-note'));
  check('Real Windows Notepad document discovered', nativeWindow && nativeWindow.process.toLowerCase() === 'notepad.exe');
  const wid = nativeWindow.window_id, sid = session.id;
  receipts.focusAfterGrant = await nativeStatus();
  const hostDigest = require('node:crypto').createHash('sha256').update(fs.readFileSync(path.join(repo, 'tools/cua-driver-win/stdio-host.cs'))).digest('hex');
  proc = spawn(path.join(repo, 'tools/cua-driver-win/.build', hostDigest + '.exe'), [python], { cwd: repo, windowsHide: true,
    env: { ...process.env, PYTHONPATH: path.join(repo, 'src'), NEYVIA_UI_BACKEND_URL: base, NEYVIA_CHAT_ID: 't16-proof', NEYVIA_APP: 'codex', NEYVIA_CHAT_TITLE: 'Native background Notepad proof' }, stdio: ['pipe', 'pipe', 'pipe'] });
  let buffer = '';
  proc.stdout.setEncoding('utf8');
  proc.stdout.on('data', chunk => { buffer += chunk; while (buffer.includes('\n')) {
    const at = buffer.indexOf('\n'), line = buffer.slice(0, at); buffer = buffer.slice(at + 1);
    if (!line.trim()) continue;
    const row = JSON.parse(line), waiter = pending.get(row.id);
    if (waiter) { pending.delete(row.id); clearTimeout(waiter.timer); row.error ? waiter.reject(new Error(JSON.stringify(row.error))) : waiter.resolve(row.result); }
  }});
  proc.stderr.on('data', chunk => { receipts.mcpStderr = String(chunk).slice(0, 1000); });
  const initialized = await rpc('initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'T16-native-agent', version: '1' } });
  check('Actual stdio MCP initialize', initialized.serverInfo.name === 'neyvia-cua');
  receipts.focusAfterMcpStart = await nativeStatus();
  const catalog = await rpc('tools/list', {});
  receipts.tools = catalog.tools.map(t => t.name);
  check('22 exact upstream tools plus five preview tools', catalog.tools.length === 27 && !catalog.tools.some(t => /perception|parse_visual/.test(t.name)));
  receipts.focusAfterDiscovery = await nativeStatus();
  const started = await tool('start_session', { session: sid });
  check('MCP binds the authorized session', started._meta?.['neyvia/preview']?.session === sid);
  let snapshot = await tool('get_window_state', { pid: nativeWindow.pid, window_id: wid });
  receipts.focusAfterNativeSnapshot = await nativeStatus();
  let doc = snapshot.structuredContent.elements.find(e => e.role === 'Document');
  check('Native accessibility projection has editable Document token', doc?.element_token && doc.actions.includes('set_value'));
  const marker = '\rMCP end-to-end native task verified through T16.';
  const typed = await tool('type_text', { pid: nativeWindow.pid, window_id: wid, element_token: doc.element_token, text: marker });
  receipts.mcpAction = compact(typed);
  check('Real agent action confirmed by UIA value readback', typed.structuredContent.effect === 'confirmed');
  const preserved = typed._meta['neyvia/preservation'];
  check('Paul foreground HWND and desktop cursor unchanged', preserved.foregroundPreserved && preserved.cursorPreserved && preserved.foregroundBefore !== String(wid));
  snapshot = await tool('get_window_state', { pid: nativeWindow.pid, window_id: wid });
  doc = snapshot.structuredContent.elements.find(e => e.role === 'Document');
  receipts.nativeReadback = { value: doc.value, windowId: wid, pid: nativeWindow.pid, token: doc.element_token, screenshot: snapshot.structuredContent.capture_id };
  check('Fresh native observation independently contains task text', doc.value.endsWith(marker));
  const predicate = { element: { selector: { role: 'Document', label_contains: doc.label }, value_equals: doc.value } };
  const verified = await tool('verify_state', { pid: nativeWindow.pid, window_id: wid, expect: [predicate], timeout_ms: 10000 });
  receipts.nativeVerification = compact(verified);
  check('Typed postcondition has two stable independent native readbacks', verified.structuredContent.status === 'satisfied' && verified.structuredContent.stable && verified.structuredContent.samples >= 2 && verified._meta['neyvia/nativeVerifier'].source.includes('ValuePattern'));
  const wrong = await tool('verify_state', { pid: nativeWindow.pid, window_id: wid, expect: [{ element: { ...predicate.element, value_equals: 'wrong value' } }], timeout_ms: 10000 });
  check('False postcondition stays unsatisfied', wrong.structuredContent.status === 'unsatisfied');
  const noStability = await tool('verify_state', { pid: nativeWindow.pid, window_id: wid, expect: [predicate], timeout_ms: 0 });
  check('Single sample cannot claim stable success', noStability.structuredContent.status === 'unknown' && noStability.structuredContent.predicates[0].unknown_reason === 'stability_unproven');
  const multiple = await tool('verify_state', { pid: nativeWindow.pid, window_id: wid, expect: [{ element: { selector: { label_contains: '' }, value_equals: '' } }], timeout_ms: 0 });
  check('Ambiguous selector is unknown instead of guessed', multiple.structuredContent.status === 'unknown' && multiple.structuredContent.predicates[0].unknown_reason === 'multi_match');
  const bad = await tool('click', { pid: nativeWindow.pid, window_id: wid, element_token: 'sdeadbeef:999' });
  check('Unknown/stale element refused before dispatch', bad.structuredContent.error.code === 'stale_element_token');
  const desktop = await tool('get_desktop_state');
  check('Unallowed desktop capture refused', desktop.structuredContent.error.code === 'app_not_allowed');
  const foreground = await tool('type_text', { pid: nativeWindow.pid, window_id: wid, element_token: doc.element_token, text: 'not dispatched', delivery_mode: 'foreground' });
  check('Foreground input refused', foreground.structuredContent.error.code === 'foreground_not_allowed');
  await http('control', { sessionId: sid, mode: 'paul' });
  const paused = await tool('type_text', { pid: nativeWindow.pid, window_id: wid, element_token: doc.element_token, text: 'not dispatched' });
  check('Take over blocks native agent input', paused.structuredContent.error.code === 'paused_by_user');
  const waiter = tool('preview_wait', { timeout_ms: 15000 });
  await http('control', { sessionId: sid, mode: 'agent', note: 'Paul checked the note. Continue.' });
  const resumed = await waiter;
  check('Give back resumes waiter and carries Paul note', resumed.structuredContent.control === 'agent' && resumed._meta['neyvia/preview'].note.includes('Paul checked'));
  snapshot = await tool('get_window_state', { pid: nativeWindow.pid, window_id: wid });
  doc = snapshot.structuredContent.elements.find(e => e.role === 'Document');
  const paul = await http('input', { sessionId: sid, windowId: wid, kind: 'type_text', element_token: doc.element_token, text: '\rPaul preview input joined the same native note.' });
  receipts.paulAction = paul;
  check('Owner preview input drives the same background native path', paul.by === 'paul' && paul.result.effect === 'confirmed' && paul.preservation.foregroundPreserved && paul.preservation.cursorPreserved);
  const feedback = await tool('preview_log', { since_seq: 0 });
  check('Agent sees Paul actions in shared log and metadata', feedback.structuredContent.entries.some(e => e.by === 'paul' && e.tool === 'type_text') && feedback._meta['neyvia/preview'].paulActions.some(e => e.tool === 'type_text'));
  snapshot = await tool('get_window_state', { pid: nativeWindow.pid, window_id: wid });
  const danger = tool('hotkey', { pid: nativeWindow.pid, window_id: wid, keys: ['shift', 'delete'] });
  const approval = await until(async () => (await state()).sessions.find(s => s.id === sid).approvals.find(a => a.kind === 'action'));
  check('Irreversible hotkey waits for owner approval', approval.tool === 'hotkey');
  await http('approve', { sessionId: sid, approvalId: approval.id, decision: 'deny' });
  const denied = await danger;
  check('Deny prevents irreversible action dispatch', denied.structuredContent.error.code === 'denied_by_user');
  await http('allow', { sessionId: sid, app: 'notepad.exe', allowed: false });
  const blocked = await tool('get_window_state', { pid: nativeWindow.pid, window_id: wid });
  check('Revoking app stops tree and frame access', blocked.structuredContent.error.code === 'app_not_allowed');
  await http('allow', { sessionId: sid, app: 'notepad.exe', allowed: true });
  await http('control', { sessionId: sid, mode: 'agent' });
  const frame = await fetch(`${base}/api/ui/cua/frame?sessionId=${sid}&windowId=${wid}`, { headers: { Cookie: cookie } });
  const bytes = Buffer.from(await frame.arrayBuffer());
  check('Real background PNG frame with capture binding and sequence', frame.ok && frame.headers.get('content-type') === 'image/png' && frame.headers.get('x-capture-id') && bytes.subarray(1, 4).toString() === 'PNG');
  fs.writeFileSync(path.join(evidence, 'T16-native-frame.png'), bytes);
  receipts.frame = { bytes: bytes.length, captureId: frame.headers.get('x-capture-id'), sequence: frame.headers.get('x-frame-seq'), sha256: require('node:crypto').createHash('sha256').update(bytes).digest('hex') };
  const sse = await fetch(`${base}/api/ui/cua/stream?sessionId=${sid}`, { headers: { Cookie: cookie }, signal: AbortSignal.timeout(10000) });
  const reader = sse.body.getReader(), first = await reader.read();
  check('Resumable real SSE exposes live session', sse.ok && new TextDecoder().decode(first.value).includes('"type": "session"'));
  await reader.cancel();
  receipts.sessionId = sid;
  receipts.window = { windowId: wid, pid: nativeWindow.pid, app: nativeWindow.app_name };
  check('Action structuredContent stays closed (Neyvia data only in metadata)', !('sessionId' in typed.structuredContent) && !('foregroundPreserved' in typed.structuredContent));
  const built = JSON.parse(fs.readFileSync(path.join(evidence, 'T16-build-launch.json')));
  check('Real native source compiled and launched without focus/cursor movement', built.foregroundPreserved && built.cursorPreserved);
  await tool('end_session'); // End the first grant before binding this MCP connection again.
  receipts.buildFocusBefore = await nativeStatus();
  const buildSession = await http('open', { apps: ['T16NativeProbe.exe'], chatId: 't16-proof', app: 'codex', title: 'Build and test native app' });
  const bs = buildSession.id, bw = built.window_id, bp = built.pid;
  let tree = await tool('get_window_state', { pid: bp, window_id: bw }, bs);
  const edit = tree.structuredContent.elements.find(e => e.label === 'Task input');
  check('Built app exposes real editable native element', edit?.element_token && edit.actions.includes('set_value'));
  const reset = await tool('set_value', { pid: bp, window_id: bw, element_token: edit.element_token, value: 'initial' }, bs);
  check('Native message route resets only the disposable edit with confirmed readback', reset.structuredContent.effect === 'confirmed' && reset._meta['neyvia/preservation'].foregroundPreserved);
  const agentEdit = await tool('type_text', { pid: bp, window_id: bw, element_token: edit.element_token, text: ' agent build cycle' }, bs);
  receipts.buildAgent = compact(agentEdit);
  check('Agent edits the newly built app in background', agentEdit.structuredContent.effect === 'confirmed' && agentEdit._meta['neyvia/preservation'].foregroundPreserved && agentEdit._meta['neyvia/preservation'].cursorPreserved);
  const paulEdit = await http('input', { sessionId: bs, windowId: bw, kind: 'type_text', text: ' Paul checked' });
  receipts.buildPaul = paulEdit;
  check('Paul text-only preview gesture reaches unique native editor', paulEdit.result.effect === 'confirmed' && paulEdit.preservation.foregroundPreserved && paulEdit.preservation.cursorPreserved);
  tree = await tool('get_window_state', { pid: bp, window_id: bw }, bs);
  check('Agent sees Paul input then continues', tree._meta['neyvia/preview'].paulActions.some(e => e.tool === 'type_text'));
  const apply = tree.structuredContent.elements.find(e => e.label === 'Apply');
  const clicked = await tool('click', { pid: bp, window_id: bw, element_token: apply.element_token }, bs);
  receipts.buildApply = compact(clicked);
  check('Agent delivers native Apply message without stealing focus', clicked.structuredContent.effect === 'unverifiable' && clicked._meta['neyvia/nativeRoute'].mechanism === 'BM_CLICK' && clicked._meta['neyvia/preservation'].foregroundPreserved && clicked._meta['neyvia/preservation'].cursorPreserved);
  const outputPath = path.join(evidence, '.t16-runtime', 'probe', 'state.result');
  await until(() => fs.existsSync(outputPath) && fs.readFileSync(outputPath, 'utf8').includes('agent build cycle Paul checked'));
  receipts.buildResult = fs.readFileSync(outputPath, 'utf8');
  receipts.buildSessionId = bs;
  check('Real built app persisted independently observed task result', receipts.buildResult === 'Applied: initial agent build cycle Paul checked');
  receipts.focusAfter = await nativeStatus();
  check('Continuous OS tracking saw zero foreground transitions during the complete built-app task', receipts.buildFocusBefore.foregroundWindowId === receipts.focusAfter.foregroundWindowId && receipts.buildFocusBefore.foregroundGeneration === receipts.focusAfter.foregroundGeneration && JSON.stringify(receipts.buildFocusBefore.cursor) === JSON.stringify(receipts.focusAfter.cursor));
}
if (require.main === module) (async () => {
  try { await main(); } catch (e) { receipts.failure = e.stack; process.exitCode = 1; }
  finally {
    if (monitor) { monitor.stdin.end(); await new Promise(resolve => { const timer = setTimeout(() => { monitor.kill(); resolve(); }, 3000); monitor.once('exit', () => { clearTimeout(timer); resolve(); }); }); }
    if (proc) { proc.stdin.end(); await new Promise(resolve => { const timer = setTimeout(() => { proc.kill(); resolve(); }, 3000); proc.once('exit', () => { clearTimeout(timer); resolve(); }); }); }
    fs.writeFileSync(path.join(evidence, 'T16.json'), JSON.stringify({ schema: 'neyvia.T16.real-native-proof.v1', at: new Date().toISOString(), passed: !receipts.failure,
      checks, receipts, boundaries: { realNativeApp: 'Windows Notepad', focusProof: 'every dispatched task action and the continuously observed built-app task; full validation environment events retained separately', physicalHumanTakeover: 'hooks attached; live physical event requires Paul', foregroundDelivery: 'explicitly refused', browserPlugin: 'Chrome and IAB unavailable; installed headless Chrome used', nas: 'pending; ports/Tailscale prohibited', published: false } }, null, 2));
    console.log(JSON.stringify({ passed: !receipts.failure, checks: checks.length, failure: receipts.failure, evidence: 'scripts/evidence/T16.json' }));
  }
})();
module.exports = { nativeStatus, stopNativeMonitor: () => monitor?.stdin.end() };
