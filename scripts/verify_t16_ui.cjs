// Uses the real preview and real Windows app; no fixtures or intercepted input.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');
const { nativeStatus, stopNativeMonitor } = require('./verify_t16.cjs');
const evidence = path.join(__dirname, 'evidence');
const native = JSON.parse(fs.readFileSync(path.join(evidence, 'T16.json')));
const sid = native.receipts.buildSessionId;
const wid = JSON.parse(fs.readFileSync(path.join(evidence, 'T16-build-launch.json'))).window_id;
const checks = [], receipts = { sessionId: sid, windowId: wid, input: [], errors: [] };
let browser, agent, agentId = 0, agentPending = new Map();
function agentRpc(method, params) {
  if (!agent) {
    const digest = require('node:crypto').createHash('sha256').update(fs.readFileSync(path.resolve(__dirname, '../tools/cua-driver-win/stdio-host.cs'))).digest('hex');
    agent = spawn(path.resolve(__dirname, '../tools/cua-driver-win/.build', digest + '.exe'), ['C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe'], { windowsHide: true, cwd: path.resolve(__dirname, '..'),
      env: { ...process.env, PYTHONPATH: path.resolve(__dirname, '../src'), NEYVIA_UI_BACKEND_URL: 'http://127.0.0.1:48171', NEYVIA_CHAT_ID: 't16-proof', NEYVIA_APP: 'codex' }, stdio: ['pipe', 'pipe', 'pipe'] });
    let buffer = '';
    agent.stdout.setEncoding('utf8');
    agent.stdout.on('data', chunk => { buffer += chunk; while (buffer.includes('\n')) {
      const at = buffer.indexOf('\n'), row = JSON.parse(buffer.slice(0, at)); buffer = buffer.slice(at + 1);
      const waiter = agentPending.get(row.id);
      if (waiter) { agentPending.delete(row.id); clearTimeout(waiter.timer); row.error ? waiter.reject(new Error(JSON.stringify(row.error))) : waiter.resolve(row.result); }
    }});
  }
  const id = ++agentId;
  return new Promise((resolve, reject) => { const timer = setTimeout(() => reject(new Error('Agent MCP timed out')), 130000); agentPending.set(id, { resolve, reject, timer }); agent.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n'); });
}
const agentTool = (name, arguments) => agentRpc('tools/call', { name, arguments });
function check(name, value) { assert.ok(value, name); checks.push({ name, passed: true }); }
async function until(fn, timeout = 30000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { if (await fn()) return; await new Promise(r => setTimeout(r, 100)); }
  throw new Error('Real preview journey timed out');
}
(async () => {
  try {
    receipts.focusBefore = await nativeStatus();
    browser = await chromium.launch({ channel: 'chrome', headless: true });
    const context = await browser.newContext({ baseURL: 'http://127.0.0.1:48172', viewport: { width: 1440, height: 1000 } });
    await context.request.post('/api/auth/local-session', { data: {} });
    const page = await context.newPage();
    page.on('pageerror', e => receipts.errors.push(e.message));
    page.on('response', async response => {
      if (response.request().method() === 'POST' && response.url().endsWith('/api/ui/cua')) {
        const payload = response.request().postDataJSON();
        if (payload.op === 'input') receipts.input.push({ payload, response: await response.json() });
      }
    });
    await page.goto('/control?ui=next', { waitUntil: 'domcontentloaded' });
    const skip = page.getByRole('button', { name: /skip for now/i });
    if (await skip.isVisible().catch(() => false)) await skip.click();
    await page.waitForTimeout(800);
    const opened = await context.request.post('/api/ui/tools/call', { data: { tool: 'neyvia.pane.show', arguments: { kind: 'preview', target: sid } } });
    check('Real product opens the native preview pane through its tool/bus', opened.ok());
    const canvas = page.getByRole('application', { name: /T16NativeProbe/ });
    await canvas.waitFor({ state: 'visible', timeout: 30000 });
    await page.waitForFunction(() => document.querySelector('.nx-pv-canvas img')?.naturalWidth > 0);
    receipts.initialImage = await canvas.locator('img').evaluate(img => ({ width: img.naturalWidth, height: img.naturalHeight, src: img.src }));
    check('Live preview renders a real native PNG', receipts.initialImage.width > 100 && receipts.initialImage.src.includes(sid) && receipts.initialImage.src.includes(String(wid)));
    await canvas.focus();
    await page.keyboard.press('Enter'); // Preview's documented typing mode.
    await page.keyboard.type(' UI joined', { delay: 35 });
    await until(() => receipts.input.some(e => e.payload.args.kind === 'type_text' && e.response.data?.result?.effect === 'confirmed'));
    check('Actual browser keyboard is forwarded to the native background editor', receipts.input.some(e => e.payload.args.text === ' UI joined' && e.response.data.result.effect === 'confirmed'));
    const snapshotResponse = await context.request.post('/api/ui/cua', { data: { op: 'snapshot', args: { sessionId: sid, windowId: wid } } });
    const tree = (await snapshotResponse.json()).data;
    const button = tree.elements.find(e => e.label === 'Apply');
    check('UI text has real native readback', tree.elements.some(e => e.label === 'Task input' && e.value.endsWith(' UI joined')));
    await page.waitForTimeout(1500);
    const rect = await canvas.boundingBox(), b = button.screenshot_frame;
    const image = await canvas.locator('img').evaluate(img => ({ width: img.naturalWidth, height: img.naturalHeight }));
    await page.mouse.click(rect.x + (b.x + b.w / 2) * rect.width / image.width, rect.y + (b.y + b.h / 2) * rect.height / image.height);
    await until(() => receipts.input.some(e => e.payload.args.kind === 'click' && e.response.data?.result?.route === 'synthetic_events'));
    const output = path.join(evidence, '.t16-runtime/probe/state.result');
    await until(() => fs.readFileSync(output, 'utf8').endsWith(' UI joined'));
    receipts.nativeResult = fs.readFileSync(output, 'utf8');
    check('Actual preview pixel click invokes native Apply and saves the result', receipts.nativeResult.endsWith(' UI joined'));
    await agentRpc('initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'T16-agent-continuation', version: '1' } });
    const seen = await agentTool('get_window_state', { window_id: wid, session: sid });
    check('Real MCP agent observes the actual UI keyboard and mouse log', seen._meta['neyvia/preview'].paulActions.some(e => e.tool === 'type_text') && seen._meta['neyvia/preview'].paulActions.some(e => e.tool === 'click'));
    let treeNow = seen, continued;
    for (let attempt = 0; attempt < 3; attempt++) {
      const edit = treeNow.structuredContent.elements.find(e => e.label === 'Task input');
      continued = await agentTool('type_text', { window_id: wid, element_token: edit.element_token, text: ' agent continued after UI' });
      if (continued.structuredContent.effect !== 'refused' || continued.structuredContent.error?.code !== 'stale_element_token') break;
      treeNow = await agentTool('get_window_state', { window_id: wid });
    }
    receipts.agentContinuation = { result: continued.structuredContent, _meta: continued._meta };
    check('Agent continues through real MCP after seeing Paul UI input', continued.structuredContent.effect === 'confirmed' && continued._meta['neyvia/preservation'].foregroundPreserved);
    treeNow = await agentTool('get_window_state', { window_id: wid });
    check('Continuation appears in the native readback', treeNow.structuredContent.elements.some(e => e.label === 'Task input' && e.value.endsWith(' agent continued after UI')));
    const expectedOutput = 'Applied: ' + treeNow.structuredContent.elements.find(e => e.label === 'Task input').value;
    let applied;
    for (let attempt = 0; attempt < 3; attempt++) {
      const buttonNow = treeNow.structuredContent.elements.find(e => e.label === 'Apply');
      applied = await agentTool('click', { window_id: wid, element_token: buttonNow.element_token });
      if (applied.structuredContent.effect !== 'refused' || applied.structuredContent.error?.code !== 'stale_element_token') break;
      treeNow = await agentTool('get_window_state', { window_id: wid });
    }
    check('Agent completes the continued native task through Apply', applied._meta['neyvia/nativeRoute']?.mechanism === 'BM_CLICK' && applied._meta['neyvia/preservation'].foregroundPreserved);
    await until(() => fs.readFileSync(output, 'utf8') === expectedOutput);
    receipts.finalNativeResult = fs.readFileSync(output, 'utf8');
    check('Independent saved result includes Paul input and agent continuation', receipts.finalNativeResult === expectedOutput);
    await page.waitForTimeout(3000); // Let the live stream render the completed app/log.
    await page.locator('.nx-pv').screenshot({ path: path.join(evidence, 'T16-preview-live.png'), animations: 'disabled', timeout: 15000 });
    receipts.focusAfter = await nativeStatus();
    check('Continuous OS hook saw zero foreground transitions and fixed cursor during UI use', receipts.focusAfter.foregroundGeneration === receipts.focusBefore.foregroundGeneration && receipts.focusAfter.foregroundWindowId === receipts.focusBefore.foregroundWindowId && JSON.stringify(receipts.focusAfter.cursor) === JSON.stringify(receipts.focusBefore.cursor));
    check('No uncaught product JavaScript error', receipts.errors.length === 0);
  } catch (e) { receipts.failure = e.stack; process.exitCode = 1; }
  finally {
    if (browser) await browser.close();
    if (agent) { agent.stdin.end(); await new Promise(resolve => { const timer = setTimeout(() => { agent.kill(); resolve(); }, 3000); agent.once('exit', () => { clearTimeout(timer); resolve(); }); }); }
    stopNativeMonitor();
    fs.writeFileSync(path.join(evidence, 'T16-ui.json'), JSON.stringify({ passed: !receipts.failure, at: new Date().toISOString(), checks, receipts }, null, 2));
    console.log(JSON.stringify({ passed: !receipts.failure, checks: checks.length, failure: receipts.failure }));
  }
})();
