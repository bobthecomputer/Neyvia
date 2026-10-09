// Real installed harness turns through the authenticated production HTTP broker.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';

const base = 'http://127.0.0.1:48331';
const root = path.resolve('.agent_control/t22/runtime');
const evidence = path.resolve('scripts/evidence/T22');
await fs.mkdir(evidence, { recursive: true });
const note = await fs.readFile(path.join(root, '.agent_control/neyvia_admin_password.txt'), 'utf8');
const password = note.match(/Password:\s*(.+)/i)?.[1]?.trim();
if (!password) throw new Error('Task-local login note unavailable');
const login = await fetch(`${base}/api/auth/login`, {
  method: 'POST', headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ username: 'admin', password }),
});
if (!login.ok) throw new Error(`Task-local login failed: ${login.status}`);
const cookie = login.headers.getSetCookie().map(value => value.split(';')[0]).join('; ');

export async function call(command, payload = {}) {
  const response = await fetch(`${base}/api/backend`, { method: 'POST', headers: { 'content-type': 'application/json', cookie }, body: JSON.stringify({ command, payload }), signal: AbortSignal.timeout(90000) });
  const value = await response.json();
  if (!response.ok || value.ok === false) throw Object.assign(new Error(value.message || value.error || `${command}: ${response.status}`), { code: value.code });
  return value.data ?? value;
}

const providers = [
  { key: 'codex', app: 'codex', model: 'gpt-6-luna', permissionMode: 'auto' },
  { key: 'claude-stream', app: 'claude-code', model: 'haiku', permissionMode: 'acceptEdits', transport: 'print' },
  { key: 'claude-terminal', app: 'claude-code', model: 'haiku', permissionMode: 'acceptEdits', transport: 'terminal' },
  { key: 'opencode', app: 'opencode', model: 'opencode-go/deepseek-v4.1-flash', permissionMode: 'workspace' },
];
const receiptPath = path.resolve('scripts/evidence/T22.json');
let receipt = { schema: 'neyvia.t22.proof.v1', startedAt: new Date().toISOString(), runtimeRoot: root, boundary: 'local worktree / authenticated production broker / installed CLIs', providers: {}, checks: {}, screenshots: [], limitations: ['No interactive Chrome/IAB plugin surface is available', 'NAS sync pending explicit port/Tailscale isolation'] };
try { receipt = JSON.parse(await fs.readFile(receiptPath, 'utf8')); } catch {}
const save = () => fs.writeFile(receiptPath, JSON.stringify(receipt, null, 2) + '\n');
const selected = process.argv.slice(2);
if (selected.includes('claude-long')) providers.push({ key: 'claude-long', app: 'claude-code', model: 'haiku', permissionMode: 'acceptEdits', transport: 'print' });
for (const provider of providers.filter(row => !selected.length || selected.includes(row.key) || selected.includes('preflight'))) {
  console.log(`T22 ${provider.key}: querying installed options`);
  let options;
  try {
    options = await call('connected_provider_options_command', { app: provider.app });
    const modelIds = (options.models || []).map(row => row.id);
    const brief = { version: options.version, modelAdvertised: modelIds.includes(provider.model), models: modelIds.filter(id => /luna|haiku|deepseek/i.test(id)), permissionModes: options.permissionModes || options.permissions, transports: options.transports };
    console.log(JSON.stringify({ provider: provider.key, options: brief }));
    receipt.providers[provider.key] = { ...(receipt.providers[provider.key] || {}), app: provider.app, model: provider.model, options: brief };
    await save();
    if (selected.includes('preflight')) continue;
    if (!modelIds.includes(provider.model) && provider.app !== 'claude-code') throw new Error('Requested model is not advertised; no substitution');
    const cwd = path.resolve(`.agent_control/t22/turns/${provider.key}-${crypto.randomUUID().slice(0, 8)}`);
    await fs.mkdir(cwd, { recursive: true });
    await fs.writeFile(path.join(cwd, 'acceptance.txt'), 'before\n');
    const message = provider.key === 'claude-long' ? 'Run exactly one Bash command that prints T22_LONG_BEGIN, then 12000 letter x characters, then T22_LONG_END. Use Python print or Bash printf. Do not edit or read files. Then reply T22_LONG_DONE. This is a disposable output transport acceptance task; do not delegate or read parent files.' : 'This is an isolated T22 transparency acceptance task. Work only in this folder. Read acceptance.txt. Use your file edit tool to replace before with after. Run a shell command that prints T22_COMMAND_OK and the file contents. Then run a shell command that exits with code 7 (intentional failure, do not repair it). Reply with T22_DONE. Use actual tools; do not delegate. Do not read any parent folder or unrelated files.';
    let cursor = (await call('connected_events_poll_command', { waitSeconds: 0 })).cursor;
    const startedAt = Date.now();
    const run = await call('connected_session_new_command', { app: provider.app, cwd, message, requestId: `t22-${crypto.randomUUID()}`, options: { model: provider.model, permissionMode: provider.permissionMode, transport: provider.transport } });
    const runId = run.runId || run.id;
    console.log(JSON.stringify({ provider: provider.key, runId, state: run.state }));
    const events = [];
    let terminal, sessionId = run.sessionId;
    const answered = new Set();
    while (Date.now() - startedAt < 240000) {
      const poll = await call('connected_events_poll_command', { cursor, waitSeconds: 3 });
      cursor = poll.cursor;
      for (const event of poll.events || []) {
        if (event.runId === runId || (sessionId && event.sessionId === sessionId)) events.push(event);
        if (event.runId !== runId) continue;
        if (event.sessionId) sessionId = event.sessionId;
        if (event.pendingRequest?.kind === 'approval' && !answered.has(event.pendingRequest.requestId)) {
          answered.add(event.pendingRequest.requestId);
          await call('connected_session_answer_command', { runId, requestId: event.pendingRequest.requestId, response: { decision: 'approve' } });
        }
        if (event.type === 'run.state' && ['completed', 'failed', 'interrupted', 'cancelled'].includes(event.state)) terminal = event;
      }
      if (terminal) break;
    }
    if (!terminal) {
      await call('connected_session_stop_command', { runId });
      throw new Error('Real turn exceeded 240 seconds; own run stopped');
    }
    const page = sessionId ? await call('connected_session_read_command', { id: sessionId, limit: 200 }) : null;
    const eventPath = path.join(evidence, `${provider.key}-events.json`);
    const pagePath = path.join(evidence, `${provider.key}-page.json`);
    await fs.writeFile(eventPath, JSON.stringify(events, null, 2) + '\n');
    await fs.writeFile(pagePath, JSON.stringify(page, null, 2) + '\n');
    const items = page?.items || [];
    const tools = items.filter(item => item.kind === 'tool');
    const reasoning = items.filter(item => item.kind === 'reasoning');
    const checks = {
      completed: terminal.state === 'completed',
      requestedModel: page?.session?.model === provider.model || (provider.app === 'claude-code' && /haiku/i.test(page?.session?.model || '')),
      actualEdit: (await fs.readFile(path.join(cwd, 'acceptance.txt'), 'utf8')).trim() === 'after',
      diff: items.some(item => item.kind === 'diff' && /[+]after/.test(item.data.patch || '')),
      commandText: tools.some(item => item.data.category === 'command' && /T22_COMMAND_OK/.test(item.data.command || item.data.input || '')),
      commandOutput: tools.some(item => /T22_COMMAND_OK/.test(item.data.output || '')),
      failureVisible: tools.some(item => item.data.exitCode === 7 || item.data.status === 'error'),
      reasoningOrExplicitNotice: reasoning.some(item => item.data.summary || item.data.notice || item.data.hidden),
      toolArguments: tools.some(item => item.data.args || item.data.input),
    };
    if (provider.key === 'claude-long') {
      for (const key of ['actualEdit', 'diff', 'commandText', 'commandOutput', 'failureVisible']) delete checks[key];
      const command = tools.find(item => item.data.category === 'command' && item.data.outputTruncated);
      const full = await call('connected_session_tool_output_command', { id: sessionId, itemId: command.id });
      checks.pageOutputBounded = command.data.outputTruncated === true && command.data.output.length <= 8192;
      checks.fullOutputPreserved = full.output.includes('x'.repeat(12000)) && full.output.includes('T22_LONG_BEGIN') && full.output.includes('T22_LONG_END') && full.truncated === false;
    }
    receipt.providers[provider.key] = { ...receipt.providers[provider.key], cwd, sessionId, runId, elapsedMs: Date.now() - startedAt, terminal, checks, kinds: [...new Set(items.map(item => item.kind))], reasoning: reasoning.map(item => ({ exposure: item.data.exposure, source: item.data.source, characters: (item.data.summary || '').length, notice: item.data.notice })), commands: tools.filter(item => item.data.category === 'command').map(item => ({ exitCode: item.data.exitCode, durationMs: item.data.durationMs, characters: (item.data.command || item.data.input || '').length, outputCharacters: (item.data.output || '').length })), events: path.relative(process.cwd(), eventPath), page: path.relative(process.cwd(), pagePath) };
    delete receipt.providers[provider.key].blocker;
    console.log(JSON.stringify({ provider: provider.key, checks, kinds: receipt.providers[provider.key].kinds, reasoning: receipt.providers[provider.key].reasoning }));
  } catch (error) {
    receipt.providers[provider.key] = { ...receipt.providers[provider.key], blocker: { code: error.code || 'proof_failed', message: error.message } };
    console.log(JSON.stringify({ provider: provider.key, blocker: error.message }));
  }
  await save();
}
receipt.updatedAt = new Date().toISOString();
await save();
if (!selected.includes('preflight')) {
  const targets = providers.filter(row => !selected.length || selected.includes(row.key));
  if (targets.some(row => receipt.providers[row.key]?.blocker || !Object.values(receipt.providers[row.key]?.checks || {}).every(Boolean))) process.exitCode = 1;
}
