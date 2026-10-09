// Real production HTTP/desktop journeys; no mocks, substituted provider or Python test suite.
import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';

const repo = resolve(import.meta.dirname, '..');
const python = 'C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe';
const previous = process.argv[2] ? JSON.parse(readFileSync(resolve(process.argv[2]), 'utf8')) : null;
const root = previous?.root ?? resolve(repo, '.agent_control', `T10-proof-${Date.now()}`);
const output = resolve(repo, 'scripts/evidence/T10.json');
const base = 'http://127.0.0.1:48241';
mkdirSync(root, { recursive: true });
const env = { ...process.env, NEYVIA_COORDINATOR_AUTOSTART: '0', FLUXIO_WATCHDOG_AUTOSTART: '0',
  NEYVIA_CONNECTED_SERVICE_PORT: '48241', NEYVIA_WEB_PORT: '48241', NEYVIA_UI_STATE_ROOT: root,
  PYTHONPATH: resolve(repo, 'src'), FLUXIO_LOCAL_SESSION_BOOTSTRAP: '1' };
let server, cookie = '', logs = '', eventCursor = 0;
const receipt = { schema: 'neyvia.T10.real-proof.v1', startedAt: new Date().toISOString(), root, port: 48241,
  model: 'gpt-6-luna', transport: 'installed Codex CLI app-server --stdio', checks: [], runs: [], events: [],
  limitations: ['UI is owned by Claude; this receipt proves backend journeys only.',
    'Token limits stop at reported usage; a transport can overshoot between events.',
    'GPU controls enforce declared requiresGpu tasks; external or undeclared workloads are not observed.',
    'NAS sync pending: the authorized isolation excludes Tailscale access.'] };
if (previous) {
  Object.assign(receipt, { startedAt: previous.startedAt, checks: previous.checks.filter(x => x.passed), runs: previous.runs,
    events: previous.events, priorFailures: [...(previous.priorFailures || []), { error: previous.error, checks: previous.checks.filter(x => !x.passed) }] });
  eventCursor = previous.events.at(-1)?.cursor ?? 0;
}
let b1 = previous?.runs[0]?.task;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const check = (name, passed, observed) => { receipt.checks.push({ name, passed: !!passed, observed }); if (!passed) throw Error(name); };
const save = () => { mkdirSync(resolve(repo, 'scripts/evidence'), { recursive: true }); writeFileSync(output, JSON.stringify(receipt, null, 2) + '\n'); };
async function http(path, body, { raw = false, auth = true } = {}) {
  const response = await fetch(base + path, { method: body === undefined ? 'GET' : 'POST',
    headers: { ...(auth && cookie ? { Cookie: cookie } : {}), ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: AbortSignal.timeout(60000) });
  const cookies = response.headers.getSetCookie();
  if (cookies.length) cookie = cookies.map(x => x.split(';')[0]).join('; ');
  const data = await response.json();
  if (raw) return { status: response.status, ...data };
  if (!response.ok || !data.ok) throw Error(`${path} ${response.status}: ${JSON.stringify(data)}`);
  return data.data ?? data;
}
const cmd = (command, payload = {}) => http('/api/backend', { command, payload });
const action = (name, body) => http(`/api/nightshift/${name}`, body);
async function pollEvents() {
  const result = await cmd('connected_events_poll_command', { cursor: eventCursor, waitSeconds: 0 });
  eventCursor = result.cursor;
  receipt.events.push(...result.events.filter(x => x.runId?.startsWith('night-')));
}
async function waitTask(id, terminal = ['done', 'blocked'], timeout = 210000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    await pollEvents();
    const task = (await action('tasks')).tasks.find(x => x.id === id);
    if (terminal.includes(task?.status)) { save(); return task; }
    await sleep(400);
  }
  throw Error(`Task ${id} never reached ${terminal}`);
}
async function startServer() {
  cookie = '';
  server = spawn(python, ['scripts/run_web_backend.py', '--host', '127.0.0.1', '--port', '48241', '--root', root, '--skip-runtime-auto-update'],
    { cwd: repo, env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  server.stdout.on('data', x => { logs += x; }); server.stderr.on('data', x => { logs += x; });
  const until = Date.now() + 90000;
  while (Date.now() < until) {
    if (server.exitCode !== null) throw Error(`Owned backend exited ${server.exitCode}`);
    try { const health = await http('/api/health', undefined, { raw: true, auth: false }); if (health.ok) break; } catch {}
    await sleep(400);
  }
  await http('/api/auth/local-session', {});
}
function stopServer() {
  if (!server || server.exitCode !== null) return;
  if (process.platform === 'win32') spawnSync('taskkill', ['/PID', String(server.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
  else server.kill('SIGTERM');
  server = null;
}
async function capturedRun(task, expectedText) {
  const run = await observedRun(task.runId);
  const transcript = await cmd('connected_session_read_command', { id: run.sessionId, limit: 100 });
  receipt.runs.push({ task, run, transcript });
  check(`real Luna run ${task.id}`, task.status === 'done' && run.state === 'completed' && JSON.stringify(transcript).includes(expectedText),
    { runId: run.runId, state: run.state, sessionId: run.sessionId, usage: run.usage, expectedText });
  return run;
}
async function observedRun(runId) {
  await pollEvents();
  const events = receipt.events.filter(x => x.runId === runId);
  const state = events.findLast(x => x.type === 'run.state');
  const usage = events.findLast(x => x.type === 'usage.updated')?.usage;
  if (!state) throw Error(`No real broker state event for ${runId}`);
  return { ...state, usage };
}
async function awaitHarness(id) {
  const task = await waitTask(id, ['running']);
  const until = Date.now() + 30000;
  while (Date.now() < until) {
    await pollEvents();
    if (receipt.events.some(x => x.runId === task.runId && x.type === 'run.state' && x.state === 'running' && x.sessionId)) return task;
    const current = (await action('tasks')).tasks.find(x => x.id === id);
    if (current.status !== 'running') throw Error(`${id} finished before its active-run gate`);
    await sleep(150);
  }
  throw Error(`${id} never acquired a real CLI session`);
}
async function extendProof() {
  const draft = id => ({ id, prompt: 'Write a detailed 6000-word essay on task scheduling. Do not use tools.', folder: root,
    harness: 'codex', model: 'gpt-6-luna', effort: 'low' });
  await action('resources', { maxTaskSeconds: null, maxNightSeconds: null, perHarnessBudgets: {}, quietGpuHours: null, gpuReservedFor: null });
  await action('create', { ...draft('Q1'), requiresGpu: true });
  await action('start', { ids: ['Q1'] });
  const activeGpu = await awaitHarness('Q1');
  const busyBegin = await http('/api/nightshift/begin', {}, { raw: true });
  check('new night refused while a CLI run is active', busyBegin.status === 400, busyBegin);
  await action('resources', { quietGpuHours: { start: '00:00', end: '00:00', timeZone: 'UTC' } });
  const gpuStopped = await waitTask('Q1', ['blocked']);
  receipt.runs.push({ task: gpuStopped, run: await observedRun(activeGpu.runId) });
  check('quiet GPU policy stops an active declared GPU CLI run', /quiet/i.test(gpuStopped.reason), gpuStopped);
  await action('resources', { quietGpuHours: null, gpuReservedFor: 'ASR', perHarnessBudgets: { codex: { maxSeconds: 1 } } });
  await action('create', draft('H1'));
  await action('start', { ids: ['H1'] });
  let h1 = (await action('summary')).tasks.find(x => x.id === 'H1');
  // Q1 time also counts: the cumulative harness cap may already be exhausted.
  if (h1.status === 'running') h1 = await waitTask('H1', ['blocked']);
  else check('cumulative harness seconds hold admission', !h1.runId && /wall time.*exhausted/i.test(h1.reason), h1);
  await action('create', draft('H2'));
  await action('start', { ids: ['H2'] });
  const h2 = (await action('summary')).tasks.find(x => x.id === 'H2');
  check('per-harness time budget holds subsequent real task', !h2.runId && /wall time.*exhausted/i.test(h2.reason), h2);
  await action('stop', { id: 'H1' }); await action('stop', { id: 'H2' });
  await action('resources', { perHarnessBudgets: {}, maxTaskSeconds: null });
  await action('create', draft('R1'));
  await action('start', { ids: ['R1'] });
  const activeRestart = await awaitHarness('R1');
  const beforeCrash = await action('summary');
  stopServer(); await sleep(1200); await startServer();
  const afterCrash = await action('summary');
  const recovered = afterCrash.tasks.find(x => x.id === 'R1');
  check('active restart blocks interrupted attempt without relaunch or duplicate accounting', recovered.status === 'blocked' && recovered.runId === activeRestart.runId && !recovered.armed && /restarted/.test(recovered.reason) && afterCrash.usage.attempts === beforeCrash.usage.attempts, { before: activeRestart, recovered, usage: afterCrash.usage });
  await action('resources', { perHarnessBudgets: { codex: { maxTokens: 1000000 } } });
  await action('create', draft('U1')); await action('start', { ids: ['U1'] });
  const unknown = (await action('summary')).tasks.find(x => x.id === 'U1');
  check('unknown interrupted usage fails closed for later token-budget admission', !unknown.runId && /unknown/i.test(unknown.reason), unknown);
  await action('stop', { id: 'U1' });
  await action('resources', { perHarnessBudgets: {}, maxNightSeconds: null });
  await action('begin', {});
  await action('resources', { maxNightSeconds: 3 });
  await action('create', draft('N1')); await action('start', { ids: ['N1'] });
  const nightStopped = await waitTask('N1', ['blocked']);
  receipt.runs.push({ task: nightStopped, run: await observedRun(nightStopped.runId) });
  check('whole-night deadline cancels a real CLI attempt', /wall time/i.test(nightStopped.reason), nightStopped);
  await action('create', draft('N2')); await action('start', { ids: ['N2'] });
  const nightHeld = (await action('summary')).tasks.find(x => x.id === 'N2');
  check('whole-night elapsed budget holds later admission', !nightHeld.runId && /Night wall time budget exhausted/.test(nightHeld.reason), nightHeld);
  await action('stop', { id: 'N2' });
  const invalidPolicy = await http('/api/nightshift/resources', { quietGpuHours: { start: '25:00', end: '00:00', timeZone: 'UTC' } }, { raw: true });
  check('invalid quiet schedule rejected without changing policy', invalidPolicy.status === 400 && (await action('resources')).quietGpuHours === null, invalidPolicy);
  receipt.finalSummary = await action('summary');
}
async function inspectProof() {
  const morning = await action('summary');
  check('final source reads persisted evidence and interruption receipts', morning.evidenceLinks.length === 3 && morning.blocked.some(x => x.id === 'R1') && morning.waitingOnPaul.some(x => x.id === 'P1'), morning);
  const immutable = await http('/api/nightshift/block', { id: 'B1', reason: 'cannot replace checked evidence' }, { raw: true });
  check('final block lock preserves completed evidence', immutable.status === 400 && (await action('tasks')).tasks.find(x => x.id === 'B1').evidence.runId === b1.runId, immutable);
  await action('resources', { perHarnessBudgets: {}, maxTaskSeconds: null, maxNightSeconds: null, quietGpuHours: null, gpuReservedFor: 'ASR' });
  for (const id of ['S1', 'S2']) await action('create', { id, prompt: 'Write a detailed 6000-word essay on task scheduling. Do not use tools.', folder: root, harness: 'codex', model: 'gpt-6-luna', effort: 'low' });
  await action('start', { ids: ['S1'] });
  const active = await awaitHarness('S1');
  await action('start', { ids: ['S2'] });
  const locked = (await action('summary')).tasks.find(x => x.id === 'S2');
  check('same-repository task reports its folder lock without a duplicate run', locked.status === 'waiting' && !locked.runId && /folder is held/.test(locked.reason), locked);
  await action('stop', { id: 'S2' }); await action('stop', { id: 'S1' });
  const stopped = await waitTask('S1', ['blocked']);
  receipt.runs.push({ task: stopped, run: await observedRun(active.runId) });
  const manual = spawnSync(python, ['scripts/build_t10_manual_contract.py'], { cwd: repo, env, windowsHide: true, encoding: 'utf8', timeout: 60000 });
  check('executable manual source grounded against all ten real handlers', manual.status === 0 && JSON.parse(manual.stdout).grounded, { exitCode: manual.status, output: manual.stdout.trim() });
  receipt.finalSummary = await action('summary');
}
try {
  await startServer();
  if (process.argv.includes('--inspect')) {
    await inspectProof();
  } else if (previous?.status === 'passed') {
    await extendProof();
  } else {
  if (!previous) {
  const unauth = await http('/api/nightshift/tasks', undefined, { raw: true, auth: false });
  check('unauthenticated task access refused', unauth.status === 401, unauth);
  await action('resources', { holdAtPlanPercent: null, perHarnessBudgets: { codex: { maxTokens: 30000, maxSeconds: 600 } }, maxNightSeconds: 900 });
  const board = '## TASKS\n- [x] A1 · Paul · needs: none · Review seed evidence\n- [ ] B1 · Codex · needs: A1 · Reply exactly T10_B1_REAL_LUNA and nothing else. Do not use tools.\n- [ ] C1 · Codex · needs: B1 · Reply exactly T10_C1_DEPENDENT and nothing else. Do not use tools.\n';
  const imported = await action('import', { text: board, folder: root, defaults: { harness: 'codex', model: 'gpt-6-luna', effort: 'low' } });
  check('TASKS import stays dormant even source checkbox', imported.tasks.every(x => x.status === 'waiting' && !x.armed && !x.runId), imported);
  await action('start', { ids: ['B1'] });
  const held = await action('tasks');
  check('prerequisite prevents launch', held.tasks.find(x => x.id === 'B1').armed && held.tasks.every(x => !x.runId), held);
  const invalid = await http('/api/nightshift/tick', { id: 'A1', evidence: { type: 'file', path: 'missing.txt' } }, { raw: true });
  check('missing completion evidence refused', invalid.status === 400, invalid);
  const file = resolve(root, 'owner-seed.txt'); writeFileSync(file, 'T10 owner acceptance evidence\n');
  const ticked = await action('tick', { id: 'A1', evidence: { type: 'file', path: file } });
  check('tick hashes real evidence', ticked.evidence.sha256 === createHash('sha256').update(readFileSync(file)).digest('hex'), ticked);
  b1 = await waitTask('B1');
  await capturedRun(b1, 'T10_B1_REAL_LUNA');
  await action('resources', { perHarnessBudgets: { codex: { maxTokens: 1, maxSeconds: 600 } } });
  await action('start', { ids: ['C1'] });
  await sleep(800);
  const capped = (await action('summary')).tasks.find(x => x.id === 'C1');
  check('cumulative harness token budget prevents dependent launch', capped.status === 'waiting' && !capped.runId && /budget.*(reached|exhausted)|token.*(reached|exhausted)/i.test(capped.reason), capped);
  await action('resources', { perHarnessBudgets: { codex: { maxTokens: 30000, maxSeconds: 600 } } });
  const c1 = await waitTask('C1');
  await capturedRun(c1, 'T10_C1_DEPENDENT');
  const changeDone = await http('/api/nightshift/block', { id: 'B1', reason: 'rewrite completion' }, { raw: true });
  check('completed evidence cannot be blocked away', changeDone.status === 400, changeDone);
  const cycle = await http('/api/nightshift/import', { text: '- [ ] D1 · Codex · needs: E1 · one\n- [ ] E1 · Codex · needs: D1 · two', folder: root }, { raw: true });
  check('cyclic import rejected atomically', cycle.status === 400 && !(await action('tasks')).tasks.some(x => x.id === 'D1'), cycle);
  await action('create', { id: 'P1', owner: 'Paul', prompt: 'Paul reviews the morning results', folder: root, needs: ['C1'] });
  await action('create', { id: 'G1', prompt: 'Reply T10_GPU_RELEASED only.', folder: root, harness: 'codex', model: 'gpt-6-luna', effort: 'low', requiresGpu: true });
  }
  await action('resources', { perHarnessBudgets: {}, gpuReservedFor: null, quietGpuHours: { start: '00:00', end: '00:00', timeZone: 'UTC' } });
  await action('start', { ids: ['G1'] });
  const quiet = (await action('summary')).tasks.find(x => x.id === 'G1');
  check('quiet GPU hours prevent declared GPU task launch', !quiet.runId && /quiet/i.test(quiet.reason), quiet);
  await action('resources', { quietGpuHours: null, gpuReservedFor: 'ASR' });
  const reserved = (await action('summary')).tasks.find(x => x.id === 'G1');
  check('ASR reservation holds declared GPU tasks', !reserved.runId && /ASR/.test(reserved.reason), reserved);
  await action('stop', { id: 'G1' });
  const beforeRestart = await action('summary');
  check('morning card evidence, waiting on Paul and measured usage', beforeRestart.waitingOnPaul.some(x => x.id === 'P1') && beforeRestart.evidenceLinks.length === 3 && beforeRestart.perHarness.codex.reportedTokens > 0 && beforeRestart.elapsedSeconds > 0, beforeRestart);
  const tool = await http('/api/ui/tools/call', { tool: 'neyvia.nightshift.summary', arguments: {} });
  check('bot tool reads the same morning state', JSON.stringify(tool).includes(b1.runId) && JSON.stringify(tool).includes('P1'), tool);
  const desktop = spawnSync(python, ['-m', 'grant_agent.desktop_bridge', '--root', root], { cwd: repo, env, windowsHide: true,
    input: JSON.stringify({ command: 'nightshift_summary_command', payload: {} }), encoding: 'utf8', timeout: 60000 });
  receipt.desktop = { exitCode: desktop.status, answer: desktop.stdout.trim(), error: desktop.stderr.slice(-1000) };
  check('fresh desktop process forwards to same persistent service', desktop.status === 0 && desktop.stdout.includes(b1.runId) && desktop.stdout.includes('P1'), receipt.desktop);
  const wrong = await http('/api/backend', { command: 'nightshift_tasks_command', payload: { _expectedStateRoot: resolve(root, 'wrong') } }, { raw: true });
  check('desktop state-root mismatch refused', wrong.status === 400, wrong);
  stopServer(); await sleep(1200); await startServer();
  const afterRestart = await action('summary');
  check('restart preserves evidence and budget usage without duplicate attempts', afterRestart.perHarness.codex.reportedTokens === beforeRestart.perHarness.codex.reportedTokens && afterRestart.evidenceLinks.length === beforeRestart.evidenceLinks.length && afterRestart.night.nightId === beforeRestart.night.nightId, afterRestart);
  await action('resources', { perHarnessBudgets: {}, maxNightSeconds: null, maxTaskSeconds: 2 });
  await action('create', { id: 'L1', prompt: 'Write a detailed 6000-word essay on task dependency scheduling. Do not use tools.', folder: root, harness: 'codex', model: 'gpt-6-luna', effort: 'low' });
  await action('start', { ids: ['L1'] });
  const limited = await waitTask('L1', ['blocked'], 90000);
  receipt.runs.push({ task: limited, run: await observedRun(limited.runId) });
  check('real CLI run cancelled on wall-time budget', /wall time|time.*(limit|reached)|seconds/i.test(limited.reason), limited);
  const night = await action('begin', {});
  const reset = await action('summary');
  check('explicit new night resets budget ledger without deleting evidence', night.nightId !== beforeRestart.night.nightId && reset.evidenceLinks.length === 3 && reset.perHarness.codex.reportedTokens === 0, reset);
  receipt.finalSummary = reset;
  }
  receipt.status = 'passed';
} catch (error) { receipt.status = 'failed'; receipt.error = String(error.stack || error); process.exitCode = 1; }
finally { stopServer(); receipt.finishedAt = new Date().toISOString(); receipt.serversStopped = true;
  const sources = ['src/grant_agent/nightshift.py', 'src/grant_agent/nightshift_import.py', 'src/grant_agent/nightshift_resources.py',
    'src/grant_agent/nightshift_ledger.py', 'src/grant_agent/nightshift_summary.py', 'src/grant_agent/neyvia_nightshift.py',
    'src/grant_agent/neyvia_workspace_tools.py', 'src/grant_agent/desktop_bridge.py', 'src/grant_agent/web_backend.py',
    'scripts/prove-t10-nightshift.mjs', 'scripts/build_t10_manual_contract.py', 'config/nightshift.manual.contract.json'];
  receipt.sourceHashes = Object.fromEntries(sources.map(path => [path, createHash('sha256').update(readFileSync(resolve(repo, path))).digest('hex')]));
  receipt.commandRegistrations = ['tasks', 'create', 'import', 'tick', 'start', 'stop', 'block', 'resources', 'summary', 'begin'].map(action => ({
    command: `nightshift_${action}_command`, http: `/api/nightshift/${action}`, tool: `neyvia.nightshift.${action}`,
    backend: 'web_backend.py dispatch + owner respond -> neyvia_nightshift -> NightShift.request',
    bot: 'neyvia_workspace_tools DEFINITIONS + call -> NativeToolRegistry',
    desktop: 'desktop_bridge allow-list + persistent forward_connected_command', tauri: 'existing generic call_desktop_backend_command IPC in lib.rs',
    ui: 'plans/15-handoff.md ## T10; Claude-owned UI remains pending' }));
  receipt.manual = { groundedSource: 'config/nightshift.manual.contract.json', tools: 10,
    pending: 'Claude copies the validated source to manuals/nightshift.manual.json, adds its index record and generates docs before claiming UI completion' };
  writeFileSync(resolve(root, 'backend.log'), logs); save();
  console.log(JSON.stringify({ status: receipt.status, passed: receipt.checks.filter(x => x.passed).length, failed: receipt.checks.filter(x => !x.passed).map(x => x.name), error: receipt.error, receipt: output, root }, null, 2)); }
