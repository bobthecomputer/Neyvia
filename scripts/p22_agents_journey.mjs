// Mounted projection contract for the production Agents dashboard, chat panel and checklist.
// The owned page server supplies finite dashboard state; this proves the React/DOM projection,
// not the connected-session backend API contract.
import { mkdir, readFile, stat, writeFile } from 'node:fs/promises';
import { dirname, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash, randomBytes } from 'node:crypto';
import { spawn } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';
import { createServer } from 'node:http';
import { build } from 'esbuild';
import { chromium } from 'playwright';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const option = name => args.includes(name) ? args[args.indexOf(name) + 1] : undefined;
const root = resolve(option('--root') || 'D:/NeyviaRuns/P22/agents-journey');
const under = (child, parent) => {
  const rel = relative(resolve(parent), resolve(child));
  return rel === '' || (!rel.startsWith('..' + sep) && rel !== '..' && !resolve(rel).startsWith(sep));
};
if (!under(root, resolve('D:/NeyviaRuns/P22')) && !under(root, resolve(repo, '.agent_control/p22'))) {
  throw new Error('Receipt root must stay under D:/NeyviaRuns/P22 or .agent_control/p22');
}
const output = resolve(root, 'agents-journey-receipt.json');
const id = 'p22.agents.checklist-dashboard-journey';
const admissionPath = 'D:/NeyviaRuns/engines/obscura-c2h/4028d3ec7e4a-d25dbe93fae7/ADMISSION.json';
const admission = JSON.parse(await readFile(admissionPath, 'utf8'));
if (admission.stealth !== false || admission.systemInstall !== false) throw new Error('Obscura must remain non-stealth and user-local');
const admissionHashes = {};
for (const key of ['engineBinary', 'workerBinary']) {
  const row = admission[key];
  const bytes = await readFile(row.path), info = await stat(row.path);
  const digest = createHash('sha256').update(bytes).digest('hex');
  if (info.size !== row.bytes || digest !== row.sha256) throw new Error(`Admitted Obscura ${key} changed`);
  admissionHashes[key] = digest;
}

const portMap = JSON.parse(process.env.NEYVIA_PROOF_PORT_MAP || 'null');
const assignedPorts = JSON.parse(process.env.NEYVIA_PROOF_ALLOWED_PORTS || '[]');
const admittedBlock = assignedPorts.length > 0 && (assignedPorts.every(port => port >= 49081 && port <= 49089)
  || assignedPorts.every(port => port >= 48871 && port <= 48889));
function proofPort(original) {
  if (![48461, 48462].includes(original)) throw new Error('Runner only requests its page and Obscura proof ports');
  const assigned = portMap?.[String(original)];
  if (!admittedBlock || !Number.isInteger(assigned) || !assignedPorts.includes(assigned)) {
    throw new Error('Both ports must resolve through the caller assigned proof port map');
  }
  return assigned;
}
const servePort = proofPort(48461), enginePort = proofPort(48462);
if (servePort === enginePort) throw new Error('Page server and Obscura need distinct assigned ports');

const component = path => resolve(repo, 'web/src/neyvia/next', path).replaceAll('\\', '/');
const entry = `
  import React from 'react';
  import { createRoot } from 'react-dom/client';
  import { NxAgentDashboard } from '${component('NxAgentDashboard.jsx')}';
  import { NxAgentsPanel } from '${component('NxAgentsPanel.jsx')}';
  import { NxChecklist } from '${component('NxChecklist.jsx')}';
  import { stageFixture, clearFixture } from '${component('nxStore.js')}';
  const roots = [];
  window.p22AgentsStage = (id, fixture) => stageFixture(id, fixture);
  window.p22AgentsClear = id => clearFixture(id);
  window.p22AgentsMount = (sessionId, rows) => {
    for (const [selector, node] of [['#dashboard', React.createElement(NxAgentDashboard, { open: true, rows, onOpenChat() {} })],
      ['#panel', React.createElement(NxAgentsPanel, { sessionId, session: { app: 'codex', capabilities: { goal: false } } })],
      ['#checklist', React.createElement(NxChecklist, { sessionId, working: true })]]) {
      const root = createRoot(document.querySelector(selector)); roots.push(root); root.render(node);
    }
  };
  window.p22AgentsUnmount = () => { for (const root of roots.splice(0)) root.unmount(); };
`;
const built = await build({
  stdin: { contents: entry, resolveDir: repo, loader: 'js' }, outdir: resolve(root, 'bundle'), bundle: true, write: false,
  format: 'iife', platform: 'browser', target: 'chrome120', sourcemap: false,
  jsx: 'automatic', define: { 'import.meta.env': '{"DEV":false}', 'process.env.NODE_ENV': '"production"' },
  logLevel: 'silent',
});
const js = built.outputFiles.find(file => file.path.endsWith('.js'))?.text;
const css = built.outputFiles.filter(file => file.path.endsWith('.css')).map(file => file.text).join('\n');
if (!js) throw new Error('Production Agents component bundle did not emit JavaScript');
await mkdir(resolve(root, 'bundle'), { recursive: true });
await writeFile(resolve(root, 'bundle/p22-agents.js'), js, 'utf8');

const epoch = new Date().toISOString();
const firstPage = Array.from({ length: 16 }, (_, index) => ({
  id: `p22-agent-${index + 1}`, app: 'codex', category: 'chat', runtime: 'codex', title: `Owned journey chat ${index + 1}`,
  status: 'working', since: epoch, now: { kind: 'plan', text: 'Next: Review the bounded task' },
  plan: { done: 1, total: 3, next: 'Review the bounded task' }, tokens: null, subagents: [],
}));
const secondPage = Array.from({ length: 2 }, (_, index) => ({
  id: `p22-agent-${index + 17}`, app: 'codex', category: 'chat', runtime: 'codex', title: `Owned journey chat ${index + 17}`,
  status: 'working', since: epoch, now: { kind: 'plan', text: 'Next: Review the bounded task' },
  plan: { done: 1, total: 3, next: 'Review the bounded task' }, tokens: null, subagents: [],
}));
const apiCalls = [];
const html = `<!doctype html><html><head><meta charset="utf-8"><style>${css}</style></head><body>
  <main><section id="dashboard"></section><section id="panel"></section><section id="checklist"></section></main>
</body></html>`;
const web = createServer(async (request, response) => {
  const url = new URL(request.url || '/', `http://127.0.0.1:${servePort}`);
  response.setHeader('cache-control', 'no-store');
  if (request.method === 'GET' && url.pathname === '/') {
    response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' }); response.end(html); return;
  }
  if (request.method === 'GET' && url.pathname === '/p22-agents.js') {
    response.writeHead(200, { 'content-type': 'text/javascript; charset=utf-8' });
    response.end(js); return;
  }
  if (request.method === 'GET' && url.pathname === '/api/ui/cua/state') {
    response.writeHead(404, { 'content-type': 'application/json' }); response.end('{"error":"not installed in this scratch harness"}'); return;
  }
  if (request.method === 'POST' && url.pathname === '/api/backend') {
    let raw = '';
    for await (const chunk of request) raw += chunk;
    const body = JSON.parse(raw || '{}');
    const command = String(body.command || '');
    const offset = Math.max(0, Number(body.payload?.offset) || 0);
    apiCalls.push({ command, offset });
    let data;
    if (command === 'connected_agents_dashboard_command') {
      const sessions = offset >= 16 ? secondPage : firstPage;
      const nextOffset = offset >= 16 ? null : 16;
      data = { sessions, total: 18, limits: [], limitProviders: [], nextOffset, hasMore: nextOffset !== null };
    } else if (command === 'conductor_list_command') data = { jobs: [] };
    else {
      response.writeHead(404, { 'content-type': 'application/json' });
      response.end(JSON.stringify({ error: 'This UI-only fixture does not implement backend semantics' })); return;
    }
    response.writeHead(200, { 'content-type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify({ ok: true, data })); return;
  }
  response.writeHead(404, { 'content-type': 'text/plain' }); response.end('Owned Agents journey observer: no resource');
});

const started = performance.now();
const report = { area: 'agents-journey', schema: 'neyvia.p22.agents-journey.v1', engine: 'admitted Obscura (headless, CDP)',
  contract: id, checks: [], failures: [], ok: false, fixtureBoundary: 'Finite dashboard response and tour: thread state exercise real mounted components only; no backend API behavior is claimed.' };
report.engineAdmission = { admission: admissionPath, version: admission.engineVersion,
  engineSha256: admissionHashes.engineBinary, workerSha256: admissionHashes.workerBinary,
  stealth: admission.stealth, systemInstall: admission.systemInstall };
await mkdir(root, { recursive: true });
const token = randomBytes(32).toString('base64url');
const profileRoot = resolve(root, 'obscura-profile'); await mkdir(profileRoot, { recursive: true });
await new Promise((listen, reject) => { web.once('error', reject); web.listen(servePort, '127.0.0.1', listen); });
const engineEnv = { ...process.env };
for (const key of Object.keys(engineEnv)) if (/API.?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH.*FILE|BASE.?URL|BROKER/i.test(key)) delete engineEnv[key];
Object.assign(engineEnv, { HOME: profileRoot, USERPROFILE: profileRoot, APPDATA: resolve(profileRoot, 'roaming'),
  LOCALAPPDATA: resolve(profileRoot, 'local'), OBSCURA_CDP_TOKEN: token, OBSCURA_ROTATE_PROFILE: '0' });
const engine = spawn(admission.engineBinary.path,
  ['serve', '--host', '127.0.0.1', '--port', String(enginePort), '--max-connections', '4', '--allow-private-network'],
  { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'], env: engineEnv });
let browser;
try {
  const deadline = Date.now() + 20000; let ready = false;
  while (Date.now() < deadline) {
    if (engine.exitCode !== null) throw new Error(`Admitted Obscura exited early (${engine.exitCode})`);
    try {
      const response = await fetch(`http://127.0.0.1:${enginePort}/json/version`,
        { headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(1500) });
      if (response.ok) { ready = true; break; }
    } catch {}
    await delay(150);
  }
  if (!ready) throw new Error(`Admitted Obscura did not become ready on assigned port ${enginePort}`);
  browser = await chromium.connectOverCDP(`http://127.0.0.1:${enginePort}`, { headers: { Authorization: `Bearer ${token}` }, timeout: 10000 });
  const page = await browser.newPage({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 1280, height: 1000 });
  await page.goto(`http://127.0.0.1:${servePort}/`, { waitUntil: 'load', timeout: 10000 });
  await page.addScriptTag({ url: `http://127.0.0.1:${servePort}/p22-agents.js` });
  await page.evaluate(() => localStorage.setItem('nx.checklist.open', JSON.stringify(false)));

  const sessionId = 'tour:p22-agents-checklist';
  const basePlan = { source: 'p22-owned-journey', explanation: 'Review, verify, and hand off the bounded task.', throughSeq: 20,
    items: [
      { id: '1', text: 'Review the current change', status: 'completed' },
      { id: '2', text: 'Validate the user outcome', status: 'pending' },
      { id: '3', text: 'Prepare a concise handoff', status: 'pending' },
    ] };
  await page.evaluate(({ sessionId, basePlan }) => {
    window.p22AgentsStage(sessionId, { thread: { plan: basePlan, planSeq: 20, items: [] } });
    window.p22AgentsMount(sessionId, []);
  }, { sessionId, basePlan });
  await page.waitForFunction(() => document.querySelector('.nx-dash-list .nx-dash-row')
    && document.querySelector('.nx-dash-sum')?.textContent.includes('18 running · showing 16'), { timeout: 8000 });

  const initialPlan = await page.locator('#checklist').evaluate(node => ({
    count: node.querySelector('.nx-checklist-count')?.textContent.trim() || '',
    headline: node.querySelector('.nx-checklist-now')?.textContent.trim() || '',
    currentClass: node.querySelector('.nx-checklist-now')?.classList.contains('is-current') || false,
    visible: (() => { const el = node.querySelector('.nx-checklist'); if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; })(),
  }));
  const pageOne = await page.locator('#dashboard').evaluate(node => ({
    heading: node.querySelector('.nx-dash-sum')?.textContent.trim() || '',
    rows: node.querySelectorAll('.nx-dash-row').length,
    first: node.querySelector('.nx-dash-title')?.textContent.trim() || '',
    more: node.querySelector('.nx-dash-more')?.textContent.trim() || '',
  }));
  const open = page.locator('#checklist .nx-checklist-head');
  await open.click();
  const planListVisible = await page.locator('#checklist .nx-checklist-list').isVisible();

  // Add an actual post-read plan operation to the production store. The mounted Checklist
  // observes it through planOf/planProgress; the fixture does not claim backend event delivery.
  const update = { id: 'p22-live-plan-update', kind: 'tool', seq: 21, at: epoch,
    data: { category: 'agent', agent: { description: 'Review the user-visible change', subagentType: 'Codex', model: 'local', status: 'running' },
      plan: { op: 'update', id: '2', status: 'in_progress', active: 'Validate the user outcome in the run view' } } };
  await page.evaluate(({ sessionId, basePlan, update }) => window.p22AgentsStage(sessionId, {
    thread: { plan: basePlan, planSeq: 20, items: [update] },
  }), { sessionId, basePlan, update });
  await page.waitForFunction(() => document.querySelector('.nx-checklist-now.is-current')?.textContent.includes('Validate the user outcome in the run view')
    && document.querySelector('#panel .nx-agent strong')?.textContent === 'Review the user-visible change', { timeout: 5000 });
  const updatedPlan = await page.locator('#checklist').evaluate(node => ({
    count: node.querySelector('.nx-checklist-count')?.textContent.trim() || '',
    headline: node.querySelector('.nx-checklist-now')?.textContent.trim() || '',
    currentClass: node.querySelector('.nx-checklist-now')?.classList.contains('is-current') || false,
    rows: [...node.querySelectorAll('.nx-checklist-item')].map(row => ({ text: row.querySelector('.nx-checklist-text')?.textContent.trim(), className: row.className })),
  }));
  const panelActive = await page.locator('#panel').evaluate(node => ({
    agent: node.querySelector('.nx-agent-main strong')?.textContent.trim() || '',
    working: node.querySelector('.nx-agents-foot .is-live')?.textContent.trim() || '',
  }));

  const more = page.locator('#dashboard .nx-dash-more');
  await more.click();
  await page.waitForFunction(() => document.querySelectorAll('.nx-dash-row').length === 18
    && document.querySelector('.nx-dash-sum')?.textContent.trim() === '18 working', { timeout: 8000 });
  const pageTwo = await page.locator('#dashboard').evaluate(node => ({
    heading: node.querySelector('.nx-dash-sum')?.textContent.trim() || '',
    rows: node.querySelectorAll('.nx-dash-row').length,
    last: node.querySelector('.nx-dash-row:last-child .nx-dash-title')?.textContent.trim() || '',
    moreButtons: node.querySelectorAll('.nx-dash-more').length,
  }));

  await page.evaluate(sessionId => window.p22AgentsStage(sessionId, {
    thread: { plan: null, planSeq: 21, items: [] },
  }), sessionId);
  await page.waitForFunction(() => !document.querySelector('#checklist .nx-checklist')
    && document.querySelector('#panel .nx-agents-empty'), { timeout: 5000 });
  const cleared = await page.locator('body').evaluate(node => ({
    checklistCount: node.querySelectorAll('.nx-checklist').length,
    completionHeadlines: [...node.querySelectorAll('.nx-checklist-now')].map(row => row.textContent.trim()).filter(text => /all done|completed/i.test(text)),
    emptyPanel: Boolean(node.querySelector('#panel .nx-agents-empty')),
  }));

  const paginationCalls = apiCalls.filter(call => call.command === 'connected_agents_dashboard_command');
  const initialOk = initialPlan.visible && initialPlan.count === '1 of 3' && initialPlan.headline === 'Next: Validate the user outcome'
    && pageOne.heading === '18 running · showing 16' && pageOne.rows === 16 && pageOne.more === 'Show 2 more of 2';
  const updateOk = planListVisible && updatedPlan.count === '1 of 3'
    && updatedPlan.headline === 'Validate the user outcome in the run view' && updatedPlan.currentClass
    && updatedPlan.rows.some(row => row.className.includes('is-current'))
    && updatedPlan.rows.some(row => row.text === 'Prepare a concise handoff' && row.className.includes('is-pending'))
    && panelActive.agent === 'Review the user-visible change' && panelActive.working.includes('1 working');
  const pageOk = pageTwo.heading === '18 working' && pageTwo.rows === 18
    && pageTwo.last === 'Owned journey chat 18' && pageTwo.moreButtons === 0
    && paginationCalls.some(call => call.offset === 0) && paginationCalls.some(call => call.offset === 16);
  const clearOk = cleared.checklistCount === 0 && cleared.completionHeadlines.length === 0 && cleared.emptyPanel;
  report.checks.push({ contract: id, name: 'mounted-checklist-update-dashboard-pagination-and-clear',
    ok: initialOk && updateOk && pageOk && clearOk,
    observed: { initialPlan, pageOne, planListVisible, updatedPlan, panelActive, pageTwo, cleared,
      paginationCalls, apiFixtureCalls: apiCalls.map(call => call.command) } });
  report.contracts = [{ id, status: initialOk && updateOk && pageOk && clearOk ? 'passed' : 'failed' }];
  report.ok = report.contracts[0].status === 'passed';
  report.executionCoverage = { available: false, reason: 'Installed Obscura CDP Profiler domain is accepted but returns no V8 precise-coverage result; DOM outcome remains directly observed.' };
  if (!report.ok) report.failures.push({ id, error: 'One or more mounted DOM outcome assertions failed.' });
  await page.evaluate(() => window.p22AgentsUnmount());
  await page.close();
} catch (error) {
  report.error = String(error?.stack || error).slice(-2500); report.failures.push({ error: report.error }); report.ok = false;
} finally {
  if (browser) await browser.close();
  engine.kill();
  let engineStopped = engine.exitCode !== null || engine.signalCode !== null;
  if (!engineStopped) engineStopped = await Promise.race([new Promise(resolveDone => engine.once('exit', () => resolveDone(true))), delay(5000).then(() => false)]);
  if (!engineStopped) { engine.kill(); engineStopped = await Promise.race([new Promise(resolveDone => engine.once('exit', () => resolveDone(true))), delay(1000).then(() => false)]); }
  const pageServerStopped = await new Promise(resolveClose => web.close(error => resolveClose(!error)));
  report.ownedProcessesStopped = engineStopped && pageServerStopped;
  if (!report.ownedProcessesStopped) { report.ok = false; report.failures.push({ error: 'Owned Obscura or page server did not stop cleanly.' }); }
}
report.status = report.ok ? 'passed' : 'failed';
report.durationMs = Math.round(performance.now() - started);
report.scratchRoot = root; report.observerPorts = { page: servePort, engine: enginePort };
report.contractCount = report.contracts?.filter(row => row.status !== 'unobserved').length || 0;
await mkdir(dirname(output), { recursive: true });
await writeFile(output, JSON.stringify(report, null, 2) + '\n', 'utf8');
process.stdout.write(JSON.stringify(report, null, args.includes('--json') ? 0 : 2) + '\n');
if (!report.ok) process.exitCode = 1;
