// Short rendered journey through production Outputs and ArtifactPane components.
// API routes are finite, local fixtures; this proves component DOM behavior only.
import { mkdir, readFile, stat, writeFile } from 'node:fs/promises';
import { dirname, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash, randomBytes } from 'node:crypto';
import { spawn } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';
import { once } from 'node:events';
import { createServer } from 'node:http';
import { build } from 'esbuild';
import { chromium } from 'playwright';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const option = name => args.includes(name) ? args[args.indexOf(name) + 1] : undefined;
const root = resolve(option('--root') || '.agent_control/p22/outputs-journey');
if (args.includes('--root') && !option('--root')) throw new Error('--root requires a scratch directory');
const under = (child, parent) => {
  const rel = relative(resolve(parent), resolve(child));
  return rel === '' || (rel !== '..' && !rel.startsWith('..' + sep) && !resolve(rel).startsWith(sep));
};
if (!under(root, resolve(repo, '.agent_control/p22')) && !under(root, resolve('D:/NeyviaRuns/P22'))) {
  throw new Error('Receipt root must stay under .agent_control/p22 or D:/NeyviaRuns/P22');
}
const output = resolve(root, 'outputs-journey-receipt.json');
const contractId = 'outputs.rendered-scratch-artifact-journey';
const selected = process.env.NEYVIA_GATE_CONTRACTS ? new Set(JSON.parse(process.env.NEYVIA_GATE_CONTRACTS)) : null;
if (selected && (selected.size !== 1 || !selected.has(contractId))) throw new Error(`NEYVIA_GATE_CONTRACTS must select only ${contractId}`);

const admissionPath = 'D:/NeyviaRuns/engines/obscura-c2h/4028d3ec7e4a-d25dbe93fae7/ADMISSION.json';
const admission = JSON.parse(await readFile(admissionPath, 'utf8'));
if (admission.stealth !== false || admission.systemInstall !== false) throw new Error('Obscura admission must be user-local and non-stealth');
const admissionHashes = {};
for (const key of ['engineBinary', 'workerBinary']) {
  const row = admission[key], bytes = await readFile(row.path), info = await stat(row.path);
  const sha256 = createHash('sha256').update(bytes).digest('hex');
  if (info.size !== row.bytes || sha256 !== row.sha256) throw new Error(`Admitted Obscura ${key} differs from its admission record`);
  admissionHashes[key] = sha256;
}

const portMap = JSON.parse(process.env.NEYVIA_PROOF_PORT_MAP || 'null');
const assignedPorts = JSON.parse(process.env.NEYVIA_PROOF_ALLOWED_PORTS || '[]');
const admittedBlock = assignedPorts.length > 0 && (assignedPorts.every(port => port >= 49081 && port <= 49089)
  || assignedPorts.every(port => port >= 48871 && port <= 48889));
function proofPort(original) {
  if (![48461, 48462].includes(original)) throw new Error('This runner only uses proofPort(48461) and proofPort(48462)');
  const assigned = portMap?.[String(original)];
  if (!admittedBlock || !Number.isInteger(assigned) || !assignedPorts.includes(assigned)) {
    throw new Error('Ports must resolve through the assigned worker block');
  }
  return assigned;
}
const servePort = proofPort(48461), enginePort = proofPort(48462);
if (servePort === enginePort) throw new Error('The page server and Obscura engine require distinct assigned ports');

await mkdir(root, { recursive: true });
const fixturePath = resolve(root, 'scratch-report.md');
const fixtureText = '# P22 finite report\n\nThis exact scratch artifact is shown in Outputs and ArtifactPane.\n';
await writeFile(fixturePath, fixtureText, 'utf8');
const fixtureBytes = Buffer.from(fixtureText, 'utf8');
const fixture = { id: 'p22-scratch-report', name: 'scratch-report.md', title: 'P22 finite report', path: fixturePath,
  kind: 'report', size: fixtureBytes.length, sha256: createHash('sha256').update(fixtureBytes).digest('hex'),
  createdAt: '2026-10-07T00:00:00.000Z', sessionId: 'p22-scratch-session' };
const observedRequests = [], apiCalls = [], externalRequests = [], refusals = [], browserErrors = [];
const entry = `
  import React from 'react';
  import { createRoot } from 'react-dom/client';
  import { NxOutputs } from '${resolve(repo, 'web/src/neyvia/next/NxOutputs.jsx').replaceAll('\\', '/')}';
  import { NxArtifactPane } from '${resolve(repo, 'web/src/neyvia/next/NxArtifactPane.jsx').replaceAll('\\', '/')}';
  import { os } from '${resolve(repo, 'web/src/neyvia/next/nxOsStore.js').replaceAll('\\', '/')}';
  let artifactRoot;
  window.p22Mount = target => {
    os.setPrefs({ revision: 1, settings: {}, network: { localOnly: true } });
    createRoot(document.querySelector('#outputs')).render(React.createElement(NxOutputs, { target: '' }));
    artifactRoot = createRoot(document.querySelector('#artifact'));
    artifactRoot.render(React.createElement(NxArtifactPane, { target }));
  };
  window.p22Reopen = target => {
    artifactRoot.unmount();
    artifactRoot = createRoot(document.querySelector('#artifact'));
    artifactRoot.render(React.createElement(NxArtifactPane, { target }));
  };
  window.p22ShowTarget = target => artifactRoot.render(React.createElement(NxArtifactPane, { target }));
`;
const built = await build({ stdin: { contents: entry, resolveDir: repo, loader: 'js' }, outdir: resolve(root, 'bundle'),
  bundle: true, write: false, format: 'iife', platform: 'browser', target: 'chrome120', sourcemap: 'inline', sourcesContent: true,
  jsx: 'automatic', define: { 'process.env.NODE_ENV': '"production"', 'import.meta.env': '{"DEV":false,"PROD":true,"MODE":"production"}' }, logLevel: 'silent' });
const js = built.outputFiles.find(file => file.path.endsWith('.js'))?.text;
const css = built.outputFiles.find(file => file.path.endsWith('.css'))?.text || '';
if (!js) throw new Error('Production Outputs/ArtifactPane bundle did not emit JavaScript');
await mkdir(resolve(root, 'bundle'), { recursive: true });
await writeFile(resolve(root, 'bundle', 'p22-outputs.js'), js, 'utf8');

const started = performance.now();
const report = { area: 'p22-outputs-journey', schema: 'neyvia.p22.outputs-journey.v1', engine: 'admitted Obscura (headless, CDP)',
  proofBoundary: 'Mounted production React components over finite intercepted local API fixtures; no remote API or publication claim',
  checks: [], failures: [], ok: false, stageTimingsMs: {}, admission: { path: admissionPath, version: admission.engineVersion,
    engineSha256: admissionHashes.engineBinary, workerSha256: admissionHashes.workerBinary, stealth: false, systemInstall: false } };
let stage = 'starting-obscura';
let stageStarted = performance.now();
const markStage = name => {
  report.stageTimingsMs[stage] = Math.round(performance.now() - stageStarted);
  stage = name;
  stageStarted = performance.now();
};
const html = `<!doctype html><html><head><meta charset="utf-8"><style>${css}</style></head><body>
  <main><section id="outputs"></section><section id="artifact"></section></main>
</body></html>`;
const web = createServer((request, response) => {
  const url = new URL(request.url || '/', `http://127.0.0.1:${servePort}`);
  if (url.pathname === '/') { response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' }); response.end(html); return; }
  if (url.pathname === '/p22-outputs.js') { observedRequests.push({ method: request.method, path: url.pathname, bytes: Buffer.byteLength(js) }); response.writeHead(200, { 'content-type': 'text/javascript; charset=utf-8' }); response.end(js); return; }
  if (request.method === 'POST' && ['/api/ui/outputs', '/api/ui/panes'].includes(url.pathname)) {
    const chunks = [];
    request.on('data', chunk => chunks.push(chunk));
    request.on('end', async () => {
      let body = {}, posted = Buffer.concat(chunks).toString('utf8');
      try { body = JSON.parse(posted || '{}'); } catch {}
      const app = url.pathname.split('/').at(-1), op = body?.op, data = body?.args || {};
      apiCalls.push({ app, op, args: data, method: request.method });
      const send = (status, value) => { response.writeHead(status, { 'content-type': 'application/json; charset=utf-8' }); response.end(JSON.stringify(value)); };
      if (app === 'outputs' && op === 'list') {
        const rows = (!data.kind || data.kind === fixture.kind) ? [fixture] : [];
        send(200, { ok: true, data: { artifacts: rows, total: rows.length } }); return;
      }
      if (app === 'outputs' && op === 'get' && data.id === fixture.id) {
        send(200, { ok: true, data: { artifact: fixture, availability: 'available' } }); return;
      }
      if (app === 'panes' && data.path === fixturePath && op === 'artifact.open') {
        send(200, { ok: true, data: { ...fixture, kind: 'markdown', text: await readFile(fixturePath, 'utf8'), version: fixture.sha256,
          modified: '2026-10-07T00:00:00.000Z' } }); return;
      }
      if (app === 'panes' && data.path === fixturePath && op === 'artifact.stat') {
        send(200, { ok: true, data: { path: fixturePath, version: fixture.sha256, modified: '2026-10-07T00:00:00.000Z' } }); return;
      }
      refusals.push({ app, op, path: data.path || null, reason: 'outside finite fixture route', posted: posted.slice(0, 300) });
      send(403, { ok: false, error: 'This journey accepts only its finite scratch artifact' });
    });
    return;
  }
  observedRequests.push({ method: request.method, path: url.pathname });
  response.writeHead(404, { 'content-type': 'application/json' }); response.end('{"ok":false,"error":"Not part of this finite fixture"}');
});
await new Promise((resolveListen, reject) => { web.once('error', reject); web.listen(servePort, '127.0.0.1', resolveListen); });
const token = randomBytes(32).toString('base64url');
const profileRoot = resolve(root, 'obscura-profile');
await mkdir(profileRoot, { recursive: true });
const engineEnv = { ...process.env };
for (const key of Object.keys(engineEnv)) if (/API.?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH.*FILE|BASE.?URL|BROKER/i.test(key)) delete engineEnv[key];
Object.assign(engineEnv, { HOME: profileRoot, USERPROFILE: profileRoot, APPDATA: resolve(profileRoot, 'roaming'),
  LOCALAPPDATA: resolve(profileRoot, 'local'), OBSCURA_CDP_TOKEN: token, OBSCURA_ROTATE_PROFILE: '0' });
const engine = spawn(admission.engineBinary.path, ['serve', '--host', '127.0.0.1', '--port', String(enginePort),
  '--max-connections', '4', '--allow-private-network'], { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'], env: engineEnv });
let browser, page;
// A single deadline covers CDP startup and every rendered step. Closing owned
// resources breaks stalled Playwright awaits; it never converts an unfinished
// step into a pass, and the receipt retains the last stage reached.
const watchdog = setTimeout(() => {
  report.timedOutAtStage = stage;
  report.timedOutAfterMs = Math.round(performance.now() - started);
  if (page) void page.close().catch(() => {});
  if (browser) void browser.close().catch(() => {});
  if (engine.exitCode === null && engine.signalCode === null) engine.kill();
  web.closeAllConnections?.();
}, 42000);
try {
  markStage('wait-obscura-ready');
  const deadline = Date.now() + 20000;
  let ready = false;
  while (Date.now() < deadline) {
    if (engine.exitCode !== null) throw new Error(`Admitted Obscura exited before readiness (${engine.exitCode})`);
    try {
      const response = await fetch(`http://127.0.0.1:${enginePort}/json/version`, { headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(1500) });
      if (response.ok) { ready = true; break; }
    } catch {}
    await delay(150);
  }
  if (!ready) throw new Error(`Admitted Obscura did not become ready on assigned port ${enginePort}`);
  markStage('connect-obscura-cdp');
  browser = await chromium.connectOverCDP(`http://127.0.0.1:${enginePort}`, { headers: { Authorization: `Bearer ${token}` }, timeout: 10000 });
  const context = await browser.newContext({ viewport: { width: 1120, height: 760 } });
  page = await context.newPage();
  page.on('pageerror', error => browserErrors.push(String(error).slice(0, 500)));
  page.on('console', message => { if (message.type() === 'error') browserErrors.push(message.text().slice(0, 500)); });
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.hostname === 'outside.invalid' || url.hostname === 'outside.example.invalid') {
      externalRequests.push(url.href);
      await route.abort(); return;
    }
    await route.continue();
  });
  await page.addInitScript(base => { window.__FLUXIO_BACKEND_URL__ = base; }, `http://127.0.0.1:${servePort}`);
  await page.goto(`http://127.0.0.1:${servePort}/`, { waitUntil: 'load', timeout: 10000 });
  await page.addScriptTag({ url: `http://127.0.0.1:${servePort}/p22-outputs.js` });
  markStage('mount-production-components');
  await page.waitForTimeout(50);
  if (!await page.evaluate(() => typeof window.p22Mount === 'function')) {
    throw new Error(`Production component bundle did not mount: ${JSON.stringify({ observedRequests, browserErrors })}`);
  }
  await page.evaluate(path => window.p22Mount(path), fixturePath);

  markStage('wait-outputs-row');
  await page.waitForFunction(() => [...document.querySelectorAll('.nx-out-row')].some(row => row.textContent.includes('P22 finite report')),
    null, { timeout: 6000 });
  const row = page.locator('.nx-out-row', { hasText: 'P22 finite report' });
  await row.click({ timeout: 4000 });
  markStage('wait-outputs-detail');
  await page.waitForFunction(() => [...document.querySelectorAll('.nx-out-detail .nx-fp-chip.is-ok')].some(node => node.textContent.includes('Same as published'))
    && document.querySelector('.nx-out-detail .nx-ap-prose')?.textContent.includes('This exact scratch artifact is shown'), null, { timeout: 6000 });
  const outputsObserved = await page.locator('.nx-out-detail').evaluate(node => ({
    title: node.querySelector('.nx-fp-name')?.textContent?.trim(),
    status: node.querySelector('.nx-fp-chip.is-ok')?.textContent?.trim(),
    content: node.querySelector('.nx-ap-prose')?.textContent?.replace(/\s+/g, ' ').trim(),
  }));
  const outputsOpenCalls = apiCalls.filter(row => row.app === 'panes' && row.op === 'artifact.open' && row.args.path === fixturePath).length;
  report.checks.push({ id: contractId, name: 'outputs-opens-local-report-with-published-status-and-content',
    ok: outputsObserved.title === fixture.title && outputsObserved.status === 'Same as published'
      && outputsObserved.content?.includes('This exact scratch artifact is shown') && outputsOpenCalls >= 1,
    observed: { ...outputsObserved, exactLocalOpenCalls: outputsOpenCalls } });

  markStage('wait-artifact-pane-content');
  await page.waitForFunction(() => document.querySelector('#artifact .nx-ap-livechip') && document.querySelector('#artifact .nx-ap .nx-ap-prose')?.textContent.includes('This exact scratch artifact is shown'), null, { timeout: 6000 });
  const firstArtifact = await page.locator('#artifact .nx-ap').evaluate(node => ({
    title: node.querySelector('.nx-fp-name')?.textContent?.trim(),
    kind: node.querySelector('.nx-fp-chip')?.textContent?.trim(),
    content: node.querySelector('.nx-ap-prose')?.textContent?.replace(/\s+/g, ' ').trim(),
  }));
  await page.evaluate(path => window.p22Reopen(path), fixturePath);
  await page.waitForFunction(() => document.querySelector('#artifact .nx-ap-livechip') && document.querySelector('#artifact .nx-ap .nx-ap-prose')?.textContent.includes('This exact scratch artifact is shown'), null, { timeout: 6000 });
  const reopenedArtifact = await page.locator('#artifact .nx-ap').evaluate(node => ({
    title: node.querySelector('.nx-fp-name')?.textContent?.trim(),
    kind: node.querySelector('.nx-fp-chip')?.textContent?.trim(),
    content: node.querySelector('.nx-ap-prose')?.textContent?.replace(/\s+/g, ' ').trim(),
  }));
  const artifactOpenCalls = apiCalls.filter(row => row.app === 'panes' && row.op === 'artifact.open' && row.args.path === fixturePath).length;
  report.checks.push({ id: contractId, name: 'artifact-pane-reopens-same-finite-content',
    ok: firstArtifact.title === fixture.name && reopenedArtifact.title === fixture.name
      && firstArtifact.kind === 'Markdown' && reopenedArtifact.kind === 'Markdown'
      && firstArtifact.content === reopenedArtifact.content && artifactOpenCalls >= 3,
    observed: { firstArtifact, reopenedArtifact, exactLocalOpenCalls: artifactOpenCalls } });

  markStage('verify-local-only-refusal');
  await page.evaluate(() => window.p22ShowTarget('https://outside.example.invalid/p22-output'));
  await page.waitForFunction(() => [...document.querySelectorAll('#artifact [role="status"]')].some(node => node.textContent.includes('Local-only is on')),
    null, { timeout: 4000 });
  const refusedText = await page.locator('#artifact').innerText();
  report.checks.push({ id: contractId, name: 'local-only-refuses-external-artifact-url',
    ok: refusedText.includes('Local-only is on') && externalRequests.length === 0,
    observed: { message: refusedText.slice(0, 500), externalRequests: [...externalRequests] } });
  report.apiBoundary = { calls: apiCalls.length, onlyFiniteLocalPathAccepted: true, refusals, externalRequests };
  report.ok = report.checks.length === 3 && report.checks.every(check => check.ok) && refusals.length === 0;
  markStage('journey-outcomes-complete');
  await page.close(); await context.close();
} catch (error) {
  report.error = String(error?.stack || error).slice(-2500);
  report.diagnostic = { apiCalls, observedRequests, browserErrors, refusals, externalRequests };
  if (page) {
    try { report.diagnostic.bodyText = (await page.locator('body').innerText()).slice(0, 1200); } catch {}
  }
  report.failures.push({ error: report.error });
  report.ok = false;
} finally {
  clearTimeout(watchdog);
  report.stageTimingsMs[stage] = Math.round(performance.now() - stageStarted);
  if (browser) await Promise.race([browser.close().then(() => true).catch(() => false), delay(1500).then(() => false)]);
  engine.kill();
  let engineStopped = engine.exitCode !== null || engine.signalCode !== null;
  if (!engineStopped) engineStopped = await Promise.race([once(engine, 'exit').then(() => true), delay(5000).then(() => false)]);
  if (!engineStopped) { engine.kill(); engineStopped = await Promise.race([once(engine, 'exit').then(() => true), delay(1000).then(() => false)]); }
  web.closeAllConnections?.();
  const serverStopped = await Promise.race([
    new Promise(resolveClose => web.close(error => resolveClose(!error))),
    delay(1500).then(() => false),
  ]);
  report.ownedProcessesStopped = engineStopped && serverStopped;
  if (!report.ownedProcessesStopped) { report.ok = false; report.failures.push({ error: 'Owned Obscura process or local server did not stop cleanly' }); }
}
report.status = report.ok ? 'passed' : 'failed';
report.contractCount = 1;
report.contracts = [{ id: contractId, status: report.ok ? 'passed' : 'failed' }];
report.scratchRoot = root;
report.scratchArtifact = { path: relative(root, fixturePath).split(sep).join('/'), sha256: fixture.sha256, bytes: fixtureBytes.length };
report.observerPorts = { page: servePort, engine: enginePort };
report.durationMs = Math.round(performance.now() - started);
await mkdir(dirname(output), { recursive: true });
await writeFile(output, JSON.stringify(report, null, 2) + '\n', 'utf8');
process.stdout.write(JSON.stringify(report, null, args.includes('--json') ? 0 : 2) + '\n');
if (!report.ok) process.exitCode = 1;
