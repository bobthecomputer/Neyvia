// Fast rendered outcomes for the production NeyviaMessageBody component.
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
const root = resolve(option('--root') || '.agent_control/p22/frontend-outcomes');
if (args.includes('--root') && !option('--root')) throw new Error('--root requires a scratch directory');
const under = (child, parent) => {
  const rel = relative(resolve(parent), resolve(child));
  return rel === '' || (!rel.startsWith('..' + sep) && rel !== '..' && !resolve(rel).startsWith(sep));
};
const localRoot = resolve(repo, '.agent_control/p22');
const externalRoot = resolve('D:/NeyviaRuns/P22');
if (!under(root, localRoot) && !under(root, externalRoot)) {
  throw new Error('Receipt root must stay under .agent_control/p22 or D:/NeyviaRuns/P22');
}
const output = resolve(root, 'frontend-outcomes-receipt.json');
const selected = process.env.NEYVIA_GATE_CONTRACTS ? new Set(JSON.parse(process.env.NEYVIA_GATE_CONTRACTS)) : null;
const ids = ['p22.message-markdown', 'p22.message-stream-safety'];
const active = id => !selected || selected.has(id);
if (selected && (!selected.size || [...selected].some(id => !ids.includes(id)))) {
  throw new Error('NEYVIA_GATE_CONTRACTS must select one or more known frontend outcome contracts');
}

const admissionPath = 'D:/NeyviaRuns/engines/obscura-c2h/4028d3ec7e4a-d25dbe93fae7/ADMISSION.json';
const admission = JSON.parse(await readFile(admissionPath, 'utf8'));
if (admission.stealth !== false || admission.systemInstall !== false) {
  throw new Error('The selected Obscura admission must remain non-stealth and user-local');
}
const admissionHashes = {};
for (const key of ['engineBinary', 'workerBinary']) {
  const row = admission[key];
  const bytes = await readFile(row.path);
  const info = await stat(row.path);
  const digest = createHash('sha256').update(bytes).digest('hex');
  if (info.size !== row.bytes || digest !== row.sha256) throw new Error(`Admitted Obscura ${key} differs from its admission record`);
  admissionHashes[key] = digest;
}
const portMap = JSON.parse(process.env.NEYVIA_PROOF_PORT_MAP || 'null');
const assignedPorts = JSON.parse(process.env.NEYVIA_PROOF_ALLOWED_PORTS || '[]');
const admittedBlock = assignedPorts.length > 0 && (assignedPorts.every(port => port >= 49081 && port <= 49089)
  || assignedPorts.every(port => port >= 48871 && port <= 48889));
function proofPort(original) {
  if (![48461, 48462].includes(original)) throw new Error('This runner only owns proofPort(48461) and proofPort(48462)');
  const assigned = portMap?.[String(original)];
  if (!admittedBlock || !Number.isInteger(assigned) || !assignedPorts.includes(assigned)) {
    throw new Error('Proof port must resolve through NEYVIA_PROOF_PORT_MAP to the caller assigned worker block');
  }
  return assigned;
}
const servePort = proofPort(48461);
const enginePort = proofPort(48462);
if (servePort === enginePort) throw new Error('The owned page server and Obscura engine require distinct assigned ports');

const entry = `
  import React from 'react';
  import { createRoot } from 'react-dom/client';
  import NeyviaMessageBody from '${resolve(repo, 'web/src/neyvia/NeyviaMessageBody.jsx').replaceAll('\\', '/')}';
  window.p22MountMessage = (host, props) => {
    const root = createRoot(document.querySelector(host));
    root.render(React.createElement(NeyviaMessageBody, props));
    return root;
  };
`;
const built = await build({
  stdin: { contents: entry, resolveDir: repo, loader: 'js' },
  outdir: resolve(root, 'bundle'),
  bundle: true,
  write: false,
  format: 'iife',
  platform: 'browser',
  target: 'chrome120',
  sourcemap: 'inline',
  sourcesContent: true,
  jsx: 'automatic',
  define: { 'process.env.NODE_ENV': '"production"' },
  logLevel: 'silent',
});
const js = built.outputFiles.find(file => file.path.endsWith('.js'))?.text;
const css = built.outputFiles.find(file => file.path.endsWith('.css'))?.text || '';
if (!js) throw new Error('Production component bundle did not emit JavaScript');
const bundlePath = resolve(root, 'bundle', 'p22-message.js');
await mkdir(dirname(bundlePath), { recursive: true });
await writeFile(bundlePath, js, 'utf8');

const started = performance.now();
const report = { area: 'p22-frontend-outcomes', schema: 'neyvia.p22.frontend-outcomes.v1', engine: 'admitted Obscura (headless, CDP)', checks: [], failures: [], ok: false };
report.engineAdmission = { admission: admissionPath, version: admission.engineVersion, engineSha256: admissionHashes.engineBinary,
  workerSha256: admissionHashes.workerBinary, stealth: admission.stealth, systemInstall: admission.systemInstall };
await mkdir(root, { recursive: true });
const token = randomBytes(32).toString('base64url');
const profileRoot = resolve(root, 'obscura-profile');
await mkdir(profileRoot, { recursive: true });
const incomingRequests = [];
const html = `<!doctype html><html><head><meta charset="utf-8"><style>${css}</style></head><body>
  <main><section id="normal"></section><section id="stream"></section><section id="hostile"></section></main>
</body></html>`;
const web = createServer((request, response) => {
  const url = new URL(request.url || '/', `http://127.0.0.1:${servePort}`);
  if (url.pathname === '/p22-message.js') {
    response.writeHead(200, { 'content-type': 'text/javascript; charset=utf-8', 'cache-control': 'no-store' });
    response.end(js);
    return;
  }
  if (url.pathname === '/') {
    response.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' });
    response.end(html);
    return;
  }
  incomingRequests.push({ method: request.method, path: url.pathname });
  response.writeHead(404, { 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'no-store' });
  response.end('Owned frontend outcome observer: no asset here');
});
await new Promise((resolveListening, reject) => {
  web.once('error', reject);
  web.listen(servePort, '127.0.0.1', resolveListening);
});
const enginePath = admission.engineBinary.path;
const engineEnv = { ...process.env };
for (const key of Object.keys(engineEnv)) {
  if (/API.?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH.*FILE|BASE.?URL|BROKER/i.test(key)) delete engineEnv[key];
}
Object.assign(engineEnv, { HOME: profileRoot, USERPROFILE: profileRoot, APPDATA: resolve(profileRoot, 'roaming'),
  LOCALAPPDATA: resolve(profileRoot, 'local'), OBSCURA_CDP_TOKEN: token, OBSCURA_ROTATE_PROFILE: '0' });
const engine = spawn(enginePath, ['serve', '--host', '127.0.0.1', '--port', String(enginePort), '--max-connections', '4', '--allow-private-network'], {
  windowsHide: true,
  stdio: ['ignore', 'ignore', 'pipe'],
  env: engineEnv,
});
let browser;
try {
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
  browser = await chromium.connectOverCDP(`http://127.0.0.1:${enginePort}`, {
    headers: { Authorization: `Bearer ${token}` }, timeout: 10000,
  });
  if (ids.every(id => !active(id))) {
    throw new Error('No selected contract produced an observable witness');
  } else {
  const page = await browser.newPage({ reducedMotion: 'no-preference' });
  const imageRequests = [];
  const cdp = await page.context().newCDPSession(page);
  const parsedScripts = new Map();
  cdp.on('Debugger.scriptParsed', event => parsedScripts.set(String(event.scriptId), { scriptId: String(event.scriptId), url: event.url || '' }));
  let coverageStarted = false;
  try {
    await cdp.send('Debugger.enable');
    await cdp.send('Profiler.enable');
    await cdp.send('Profiler.startPreciseCoverage', { callCount: true, detailed: true });
    coverageStarted = true;
  } catch (error) {
    report.executionCoverage = { available: false, reason: String(error).slice(0, 400) };
  }
  await cdp.send('Network.enable');
  cdp.on('Network.requestWillBeSent', event => {
    if (event.request.url.includes('/__p22_image_must_not_load__.png')) imageRequests.push(event.request.url);
  });
  await page.goto(`http://127.0.0.1:${servePort}/`, { waitUntil: 'load', timeout: 10000 });
  await page.addScriptTag({ url: `http://127.0.0.1:${servePort}/p22-message.js` });

  const markdown = `## Release notes\nA **fast** path with \`npm run gate\`.\n\n![Preview](http://127.0.0.1:${servePort}/__p22_image_must_not_load__.png)`;
  if (active('p22.message-markdown')) {
    await page.evaluate(({ markdown }) => window.p22MountMessage('#normal', { text: markdown }), { markdown });
    await page.waitForFunction(() => document.querySelector('#normal h2'));
    const normal = await page.locator('#normal .neyvia-message-body').evaluate(node => ({
      heading: node.querySelector('h2')?.textContent || '',
      emphasis: node.querySelector('strong')?.textContent || '',
      code: node.querySelector('code')?.textContent || '',
      preview: [...node.querySelectorAll('a')].map(link => ({ text: link.textContent, href: link.href })),
      images: node.querySelectorAll('img').length,
      visible: (() => { const rect = node.getBoundingClientRect(), style = getComputedStyle(node); return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none'; })(),
    }));
    const normalOk = normal.heading === 'Release notes' && normal.emphasis === 'fast' && normal.code === 'npm run gate'
      && normal.preview.length === 1 && normal.preview[0].text === 'Preview'
      && normal.preview[0].href === `http://127.0.0.1:${servePort}/__p22_image_must_not_load__.png`
      && normal.images === 0 && normal.visible && imageRequests.length === 0;
    const requestObserverControl = new Promise(resolveObserved => {
      const timeout = setTimeout(() => resolveObserved(false), 1500);
      const check = event => {
        if (!event.request.url.includes('/__p22_request_observer_control__.png')) return;
        clearTimeout(timeout);
        resolveObserved(true);
      };
      cdp.on('Network.requestWillBeSent', check);
    });
    await page.evaluate(port => {
      const probe = new Image();
      probe.id = 'p22-request-observer-control';
      probe.src = `http://127.0.0.1:${port}/__p22_request_observer_control__.png`;
      document.body.append(probe);
    }, servePort);
    await page.waitForFunction(() => document.querySelector('#p22-request-observer-control')?.complete, { timeout: 3000 });
    const nativeEventObserved = await requestObserverControl;
    const networkObserved = incomingRequests.some(row => row.path === '/__p22_request_observer_control__.png');
    const forbiddenServerRequests = incomingRequests.filter(row => row.path === '/__p22_image_must_not_load__.png');
    report.checks.push({ contract: 'p22.message-markdown', name: 'markdown-output-and-no-background-image-load',
      ok: normalOk && networkObserved && forbiddenServerRequests.length === 0, observed: { normal, forbiddenImageRequests: [...imageRequests],
        nativeRequestEvent: nativeEventObserved,
        ownedServerObservedPositiveControl: networkObserved,
        forbiddenServerRequests,
        observerProbe: await page.locator('#p22-request-observer-control').evaluate(node => ({ complete: node.complete, naturalWidth: node.naturalWidth,
          resourceSeen: performance.getEntriesByName(node.src).length > 0 })) } });
  }

  if (active('p22.message-stream-safety')) {
    await page.evaluate(() => {
      window.p22MountMessage('#stream', { text: 'Partial **bold phrase', streaming: true, revealKey: 'p22-stream' });
      window.p22MountMessage('#hostile', { text: '<script>window.p22Injected = true</script>\n\nVisible after rejected markup' });
    });
    await page.waitForFunction(() => document.querySelector('#stream .neyvia-message-body[data-streaming="true"]') && document.querySelector('#hostile .neyvia-message-body'));
    await page.waitForTimeout(40);
    const streaming = await page.locator('#stream .neyvia-message-body').evaluate(node => ({
      text: node.textContent.trim(), streaming: node.dataset.streaming === 'true', rawMarker: node.textContent.includes('**'),
      revealedWords: node.querySelectorAll('.nv-w').length,
    }));
    const streamingOk = streaming.text === 'Partial' && streaming.streaming && !streaming.rawMarker && streaming.revealedWords > 0;
    const hostile = await page.locator('#hostile .neyvia-message-body').evaluate(node => ({
      text: node.textContent.trim(), scripts: node.querySelectorAll('script').length, images: node.querySelectorAll('img').length,
    }));
    const hostileOk = hostile.text.includes('Visible after rejected markup') && hostile.scripts === 0 && hostile.images === 0
      && await page.evaluate(() => window.p22Injected !== true);
    report.checks.push({ contract: 'p22.message-stream-safety', name: 'partial-stream-and-raw-html-refusal', ok: streamingOk && hostileOk, observed: { streaming, hostile } });
  }
  const failed = report.checks.filter(check => !check.ok);
  report.failures = failed.map(check => ({ id: check.contract, error: check.name }));
  report.contracts = ids.filter(active).map(id => ({ id, status: failed.some(check => check.contract === id)
    || (id === 'p22.message-markdown' && imageRequests.length > 0) ? 'failed' : 'passed' }));
  report.contracts.push(...ids.filter(id => !active(id)).map(id => ({ id, status: 'unobserved' })));
  report.ok = report.contracts.filter(row => row.status !== 'unobserved').length > 0
    && report.contracts.every(row => row.status === 'passed' || row.status === 'unobserved');
  if (coverageStarted && report.ok) {
    const captured = await cdp.send('Profiler.takePreciseCoverage');
    await cdp.send('Profiler.stopPreciseCoverage');
    const coverageEntries = captured?.result;
    if (!Array.isArray(coverageEntries)) {
      report.executionCoverage = { available: false, reason: 'Obscura Profiler.takePreciseCoverage returned no V8 result array', responseKeys: Object.keys(captured || {}) };
    }
    const scriptRows = [];
    for (const item of coverageEntries || []) {
      const metadata = parsedScripts.get(String(item.scriptId));
      if (!metadata) continue;
      try {
        const body = await cdp.send('Debugger.getScriptSource', { scriptId: item.scriptId });
        scriptRows.push({ ...metadata, source: body.scriptSource });
      } catch {}
    }
    const rawPath = resolve(root, 'v8-coverage-raw.json');
    const mappedPath = resolve(root, 'v8-coverage-source.json');
    await mkdir(resolve(root, 'bundle'), { recursive: true });
    const passingContracts = report.contracts.filter(row => row.status === 'passed').map(row => row.id);
    await writeFile(rawPath, JSON.stringify({ result: coverageEntries, scripts: scriptRows, contracts: passingContracts,
      measurementUnit: { kind: 'grouped-outcome-journey', contracts: passingContracts, perContractAttribution: false },
      cdpResponseKeys: Object.keys(captured || {}) }) + '\n', 'utf8');
    if (!Array.isArray(coverageEntries)) {
      report.measurementUnavailable = report.executionCoverage.reason;
    } else {
    const mapper = spawn('node', [resolve(repo, 'scripts/p22_v8_coverage.mjs'), '--raw', rawPath,
      '--build', resolve(root, 'bundle'), '--repo', repo, '--out', mappedPath], {
      cwd: repo, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env },
    });
    let mapperOut = '', mapperErr = '';
    mapper.stdout.setEncoding('utf8'); mapper.stderr.setEncoding('utf8');
    mapper.stdout.on('data', chunk => { mapperOut = (mapperOut + chunk).slice(-4000); });
    mapper.stderr.on('data', chunk => { mapperErr = (mapperErr + chunk).slice(-4000); });
    const [mapperCode] = await once(mapper, 'exit');
    if (mapperCode === 0) {
      report.executionCoverage = { available: true, raw: relative(root, rawPath), sourceMapped: relative(root, mappedPath),
        contracts: JSON.parse(mapperOut.split(/\r?\n/).filter(Boolean).at(-1)).contracts };
    } else {
      report.executionCoverage = { available: false, reason: `source-map mapper exited ${mapperCode}: ${mapperErr || mapperOut}` };
      report.measurementUnavailable = report.executionCoverage.reason;
    }
    }
  } else if (coverageStarted) {
    await cdp.send('Profiler.stopPreciseCoverage').catch(() => {});
    report.executionCoverage = { available: false, reason: 'coverage attached only to passing outcome contracts', contracts: [] };
  } else {
    report.executionCoverage = { available: false, reason: 'Obscura precise coverage did not start before the outcome journey', contracts: [] };
  }
  await page.close();
  }
} catch (error) {
  report.error = String(error?.stack || error).slice(-2500);
  report.ok = false;
  report.failures.push({ error: report.error });
} finally {
  if (browser) await browser.close();
  engine.kill();
  let engineStopped = engine.exitCode !== null || engine.signalCode !== null;
  if (!engineStopped) {
    engineStopped = await Promise.race([once(engine, 'exit').then(() => true), delay(5000).then(() => false)]);
    if (!engineStopped) {
      engine.kill();
      engineStopped = await Promise.race([once(engine, 'exit').then(() => true), delay(1000).then(() => false)]);
    }
  }
  const pageServerStopped = await new Promise(resolveClose => web.close(error => resolveClose(!error)));
  report.ownedProcessesStopped = engineStopped && pageServerStopped;
  if (!report.ownedProcessesStopped) {
    report.ok = false;
    report.failures.push({ error: 'An owned headless process or local server did not stop cleanly' });
  }
}
report.status = report.ok ? 'passed' : 'failed';
report.scratchRoot = root;
report.observerPorts = { page: servePort, engine: enginePort };
report.contractCount = report.contracts?.filter(row => row.status !== 'unobserved').length || 0;
report.durationMs = Math.round(performance.now() - started);
await mkdir(dirname(output), { recursive: true });
await writeFile(output, JSON.stringify(report, null, 2) + '\n', 'utf8');
process.stdout.write(JSON.stringify(report, null, args.includes('--json') ? 0 : 2) + '\n');
if (!report.ok) process.exitCode = 1;
