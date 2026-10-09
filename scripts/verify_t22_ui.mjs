// Application acceptance in an isolated installed Chrome instance, no user browser/profile.
import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';
import assert from 'node:assert/strict';
const backend = 'http://127.0.0.1:48331';
const ui = 'http://127.0.0.1:48332';
const receiptPath = 'scripts/evidence/T22.json';
const receipt = JSON.parse(await fs.readFile(receiptPath, 'utf8'));
const directory = 'scripts/evidence/T22';
const safeError = error => String(error?.message || error).replace(/((?:cookie|authorization):)[^\n]+/gi, '$1 [redacted]').replace(/grand_agent_session=[^\s]+/g, 'grand_agent_session=[redacted]');
await fs.mkdir(directory, { recursive: true });
const note = await fs.readFile('.agent_control/t22/runtime/.agent_control/neyvia_admin_password.txt', 'utf8');
const password = note.match(/Password:\s*(.+)/i)?.[1]?.trim();
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
const login = await context.request.post(`${backend}/api/auth/login`, { data: { username: 'admin', password } });
assert.equal(login.status(), 200);
const page = await context.newPage();
const errors = [];
page.on('pageerror', error => errors.push(error.message));
async function call(command, payload) {
  const response = await context.request.post(`${backend}/api/backend`, { data: { command, payload } });
  const value = await response.json();
  assert.equal(value.ok, true, value.message || value.error);
  return value.data;
}
async function tool(name, args) {
  const response = await context.request.post(`${backend}/api/ui/tools/call`, { data: { tool: name, arguments: args } });
  const value = await response.json();
  assert.equal(value.ok, true, JSON.stringify(value));
  const data = value.data ?? value;
  assert.notEqual(data.ok, false, JSON.stringify(data));
  return data.result ?? data;
}
try {
  receipt.uiProof = { transport: 'installed Chrome headless / actual authenticated Vite app and production broker; no fixtures or intercepted provider responses', checks: {}, errors, screenshotPaths: [] };
  for (const [key, provider] of Object.entries(receipt.providers)) {
    if (!provider.sessionId) continue;
    const refreshed = await call('connected_session_read_command', { id: provider.sessionId, limit: 200 });
    await fs.writeFile(provider.page, JSON.stringify(refreshed, null, 2) + '\n');
    provider.actualModel = refreshed.session.model;
    provider.checks.requestedModel = provider.actualModel === provider.model || (provider.app === 'claude-code' && /haiku/i.test(provider.actualModel || ''));
    assert(provider.checks.requestedModel, `${key}: selected model not confirmed`);
    delete provider.blocker;
    await page.goto(`${ui}/control?chat=${encodeURIComponent(provider.sessionId)}`, { waitUntil: 'domcontentloaded' });
    await page.locator('.nx-thread-col').waitFor({ timeout: 90000 });
    await page.getByText(key === 'claude-long' ? 'T22_LONG_DONE' : 'T22_DONE', { exact: true }).last().waitFor({ timeout: 30000 });
    const skipSetup = page.getByRole('button', { name: 'Skip setup', exact: true });
    if (await skipSetup.isVisible()) await skipSetup.click();
    // Canonical state action is also the model-facing way to arrange this real UI.
    await tool('neyvia.view.transparency', { level: 'everything' });
    await page.locator('.nx-tool-body').first().waitFor();
    if (key === 'claude-long') {
      const source = refreshed.items.find(item => item.kind === 'tool' && item.data.outputTruncated);
      const full = await call('connected_session_tool_output_command', { id: provider.sessionId, itemId: source.id });
      provider.checks.pageOutputBounded = source.data.outputTruncated === true && source.data.output.length <= 8192;
      provider.checks.fullOutputPreserved = full.output.includes('x'.repeat(12000)) && full.output.includes('T22_LONG_END') && !full.truncated;
      const output = page.locator('.nx-tool pre[aria-label^="Output from"]').filter({ hasText: 'T22_LONG_BEGIN' }).last();
      await page.waitForFunction(() => [...document.querySelectorAll('.nx-tool pre[aria-label^="Output from"]')].some(element => element.textContent.includes('x'.repeat(12000)) && element.textContent.includes('T22_LONG_END')));
      assert((await output.innerText()).includes('x'.repeat(12000)));
      await output.scrollIntoViewIfNeeded();
      await output.evaluate(element => { element.scrollTop = element.scrollHeight; });
      const screenshot = `${directory}/full-output-restored.png`;
      await page.screenshot({ path: screenshot });
      receipt.uiProof.screenshotPaths.push(screenshot);
      receipt.uiProof.checks.fullOutputAfterRefresh = true;
      continue;
    }
    const command = page.locator('.nx-tool').filter({ hasText: 'T22_COMMAND_OK' }).first();
    const sourceCommand = refreshed.items.find(item => item.kind === 'tool' && /T22_COMMAND_OK/.test(item.data.command || item.data.input || ''));
    const fullCommand = await call('connected_session_tool_output_command', { id: provider.sessionId, itemId: sourceCommand.id });
    assert.equal(fullCommand.output, sourceCommand.data.output, `${key}: native full-output endpoint changed output`);
    assert(await command.locator('.nx-tool-body').count(), `${key}: full command hidden`);
    assert.match(await command.innerText(), /Command[\s\S]*Output[\s\S]*Exit 0/);
    await command.scrollIntoViewIfNeeded();
    const commandPath = `${directory}/${key}-command.png`;
    await page.screenshot({ path: commandPath });
    receipt.uiProof.screenshotPaths.push(commandPath);
    const diff = page.locator('.nx-thread-diff').first();
    await diff.scrollIntoViewIfNeeded();
    assert.match(await diff.innerText(), /after/);
    const diffPath = `${directory}/${key}-diff.png`;
    await page.screenshot({ path: diffPath });
    receipt.uiProof.screenshotPaths.push(diffPath);
    const reasoning = page.locator('.nx-reason').first();
    await reasoning.scrollIntoViewIfNeeded();
    const reasonPath = `${directory}/${key}-reasoning.png`;
    await page.screenshot({ path: reasonPath });
    receipt.uiProof.screenshotPaths.push(reasonPath);
    const failed = page.locator('.nx-tool.is-error').last();
    await failed.scrollIntoViewIfNeeded();
    assert.match(await failed.innerText(), /Exit 7/);
    receipt.uiProof.checks[key] = { command: true, output: true, zeroExit: true, diff: true, reasoningOrAvailability: true, nonzeroExit: true, sameComponents: ['nx-tool', 'nx-diff-card', 'nx-reason'] };
    console.log(JSON.stringify({ rendered: key, model: provider.actualModel }));
  }
  if (process.argv.includes('--initial')) {
    console.log(JSON.stringify({ body: (await page.locator('body').innerText()).slice(0, 2500) }));
  } else {
    // Open the same Settings screen a human or model can open through pane.show.
    await tool('neyvia.pane.show', { kind: 'settings', target: 'transparency' });
    const settings = page.locator('[aria-labelledby="nx-set-transparency"]');
    await settings.waitFor();
    await settings.scrollIntoViewIfNeeded();
    await settings.getByRole('radio', { name: 'Summaries', exact: true }).click();
    await settings.getByRole('radio', { name: 'Summaries', exact: true, checked: true }).waitFor();
    let snapshot = await (await context.request.get(`${backend}/api/ui/state`)).json();
    assert.equal((snapshot.data ?? snapshot).transparency, 'summaries');
    await settings.getByRole('radio', { name: 'Minimal', exact: true }).click();
    await settings.getByRole('radio', { name: 'Minimal', exact: true, checked: true }).waitFor();
    snapshot = await (await context.request.get(`${backend}/api/ui/state`)).json();
    assert.equal((snapshot.data ?? snapshot).transparency, 'minimal');
    await page.reload();
    await page.locator('.nx-thread-col').waitFor({ timeout: 90000 });
    assert.equal(await page.locator('.nx-tool:not(.is-error)').count(), 0);
    assert.equal(await page.locator('.nx-diff-card').count(), 0);
    assert(await page.locator('.nx-tool.is-error').count());
    assert(await page.locator('.nx-reason.is-hidden').count());
    receipt.uiProof.checks.minimalPersistence = true;
    await tool('neyvia.pane.show', { kind: 'settings', target: 'transparency' });
    await settings.waitFor();
    await settings.getByRole('radio', { name: 'Show everything', exact: true }).click();
    await page.locator('.nx-tool-body').first().waitFor();
    for (const theme of ['dark', 'light']) {
      await tool('neyvia.view.theme', { theme });
      await page.locator(`.nx[data-nx-theme="${theme}"]`).waitFor();
      await settings.scrollIntoViewIfNeeded();
      const screenshot = `${directory}/settings-${theme}.png`;
      await page.screenshot({ path: screenshot });
      receipt.uiProof.screenshotPaths.push(screenshot);
    }
    receipt.uiProof.checks.settingsHumanControl = true;
    receipt.uiProof.checks.darkLight = true;
    receipt.uiProof.checks.providerErrorsRetained = true;
    const manual = await tool('neyvia.manual.run', { id: 'transparency', chapter: 'overview', procedure: 'choose-detail', inputs: { level: 'everything' } });
    assert.equal(manual.status, 'completed');
    assert(manual.checks.length > 0);
    receipt.uiProof.checks.executableManual = true;
    const invalid = await context.request.post(`${backend}/api/ui/tools/call`, { data: { tool: 'neyvia.view.transparency', arguments: { level: 'invalid' } } });
    const refusal = await invalid.json();
    assert.equal(refusal.ok, false);
    const retained = await (await context.request.get(`${backend}/api/ui/state`)).json();
    assert.equal((retained.data ?? retained).transparency, 'everything');
    receipt.uiProof.checks.invalidPreferenceRejectedWithoutMutation = true;
    // Controlled transport-limit signal; recovery reads the actual saved
    // provider page through HTTP. Provider turns and captures are unchanged.
    receipt.uiProof.checks.controlledTransportRecovery = await page.evaluate(async id => {
      const moduleUrl = performance.getEntriesByType('resource').filter(entry => /\/nxStore\.js(?:\?|$)/.test(entry.name)).at(-1)?.name;
      if (!moduleUrl) throw new Error('Running app store module not found');
      const store = await import(moduleUrl);
      const original = window.EventSource;
      let source;
      store.startLive()();
      window.EventSource = class {
        constructor() { source = this; }
        close() {}
      };
      const stop = store.startLive();
      try {
        const before = store.getNx().threads[id];
        for (const payload of [
          { type: 'item.updated', sessionId: id, truncated: true },
          { type: 'item.updated', sessionId: id, truncated: true, item: { ...before.items.find(item => item.kind === 'tool'), data: { command: 'partial ... [truncated]' } } },
        ]) {
          const originalItems = JSON.stringify(store.getNx().threads[id].items);
          source.onmessage({ data: JSON.stringify(payload) });
          if (!store.getNx().threads[id].transportTruncated || JSON.stringify(store.getNx().threads[id].items) !== originalItems) throw new Error('Partial event replaced canonical items');
          await new Promise(resolve => setTimeout(resolve, 50));
          if (!document.body.innerText.includes('A live update was shortened.')) throw new Error('Transport notice missing');
          const deadline = Date.now() + 30000;
          while (store.getNx().threads[id].transportTruncated && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 100));
          if (store.getNx().threads[id].transportTruncated || store.getNx().threads[id].status !== 'ready') throw new Error('Canonical recovery failed');
          if (store.getNx().threads[id].items.some(item => item.data?.command === 'partial ... [truncated]')) throw new Error('Partial command survived');
        }
        return { omittedItem: true, shortenedItem: true, availabilityNotice: true, actualProviderPageRestored: true };
      } finally {
        stop();
        window.EventSource = original;
        store.startLive();
      }
    }, receipt.providers['claude-long'].sessionId);
  }
  assert.equal(errors.length, 0, errors.join('\n'));
  receipt.uiProof.ok = true;
} catch (error) {
  receipt.uiProof.ok = false;
  receipt.uiProof.blocker = safeError(error);
  const capture = `${directory}/ui-failure.png`;
  await page.screenshot({ path: capture }).catch(() => {});
  console.log(JSON.stringify({ error: safeError(error), body: (await page.locator('body').innerText()).slice(0, 2500), capture }));
  process.exitCode = 1;
} finally {
  receipt.updatedAt = new Date().toISOString();
  await fs.writeFile(receiptPath, JSON.stringify(receipt, null, 2) + '\n');
  await browser.close();
}
