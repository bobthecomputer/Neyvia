// Headless user journeys against the owned running app. No provider responses are mocked.
import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const bug = Number(process.argv[2] || 3);
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  page.on('pageerror', e => console.error('PAGE', e.message));
  await page.request.post('http://127.0.0.1:48902/api/auth/local-session', { data: {} });
  await page.goto('http://127.0.0.1:48902/control', { waitUntil: 'domcontentloaded' });
  const skip = page.getByRole('button', { name: 'Skip setup', exact: true });
  await skip.waitFor({ timeout: 1500 }).then(() => skip.click()).catch(() => {});
  if (bug === 4) {
    const saved = JSON.parse(await fs.readFile('.agent_control/dogfix/contracts/steered-session.json', 'utf8'));
    await page.locator('.nx-folder-trigger').waitFor({ timeout: 45000 });
    await page.getByRole('radio', { name: 'Codex', exact: true }).click();
    await page.locator('.nx-folder-trigger').click();
    await page.getByRole('textbox', { name: 'Search folders', exact: true }).fill(saved.cwd);
    await page.getByRole('option', { name: /Use this folder/ }).click();
    const worktree = page.locator('.nx-worktree input[type=checkbox]');
    if (await worktree.count()) await worktree.uncheck();
    await page.getByRole('textbox', { name: 'First message' }).fill('No file edits or agents. Run PowerShell Start-Sleep -Seconds 12, then reply ORIGINAL-UI-DOGFIX.');
    await page.getByRole('button', { name: 'Start chat', exact: true }).click();
    const input = page.locator('form.nx-composer textarea');
    await input.waitFor({ timeout: 45000 });
    await page.waitForFunction(() => document.querySelector('form.nx-composer textarea')?.placeholder.includes('Steer'), null, { timeout: 45000 });
    await input.fill('Change the final reply to STEERED-UI-DOGFIX. No more tools or file edits.');
    await page.getByRole('button', { name: 'Steer', exact: true }).click();
    await page.locator('.nx-msg-assistant').filter({ hasText: 'STEERED-UI-DOGFIX' }).waitFor({ timeout: 60000 });
    assert.equal(await page.getByText('Codex cannot take a message into a running turn', { exact: false }).count(), 0);
    await page.screenshot({ path: 'scripts/evidence/DOGFIX-4.png' });
    await fs.writeFile('scripts/evidence/DOGFIX-steering-rendered.json', JSON.stringify({ passed: true, chat: new URL(page.url()).searchParams.get('chat'), result: 'STEERED-UI-DOGFIX' }, null, 2));
    console.log('Real composer steering changed the running Codex turn');
  } else if (bug === 6) {
    const saved = JSON.parse(await fs.readFile('scripts/evidence/DOGFIX-worktree-rendered.json', 'utf8'));
    await page.goto('http://127.0.0.1:48902/control?chat=' + encodeURIComponent(saved.chat));
    await page.locator('.nx-msg-assistant').filter({ hasText: 'NEXT-DRAFT-DOGFIX' }).waitFor({ timeout: 45000 });
    const name = saved.ready.path.split(/[\\/]/).pop();
    await page.getByRole('group', { name, exact: true }).locator(`[data-session-id="${saved.chat}"]`).waitFor({ timeout: 45000 });
    const snapshot = await page.request.get('http://127.0.0.1:48902/api/ui/state').then(r => r.json());
    const state = snapshot.data || snapshot;
    assert.equal(state.sessions[saved.chat].project, saved.ready.path);
    assert.equal(state.projects[saved.ready.path].path, saved.ready.path);
    await page.screenshot({ path: 'scripts/evidence/DOGFIX-6.png' });
    console.log('Saved chat and durable chosen-folder placement survive a fresh browser');
  } else if (bug === 9) {
    const fixture = JSON.parse(await fs.readFile('.agent_control/dogfix/contracts/progress-fixture.json', 'utf8'));
    await page.locator('.nx-folder-trigger').waitFor({ timeout: 45000 });
    await page.getByRole('radio', { name: 'Codex', exact: true }).click();
    await page.locator('.nx-folder-trigger').click();
    await page.getByRole('textbox', { name: 'Search folders', exact: true }).fill(fixture.path);
    await page.getByRole('option', { name: /Use this folder/ }).click();
    await page.locator('.nx-worktree input[type=checkbox]').check();
    const branch = 'progress-' + Date.now();
    await page.getByRole('textbox', { name: 'New branch name' }).fill(branch);
    const initial = 'No tools, file edits or agents. Reply WORKTREE-DOGFIX.';
    const next = 'No tools, file edits or agents. Reply NEXT-DRAFT-DOGFIX.';
    const composer = page.getByRole('textbox', { name: 'First message' });
    await composer.fill(initial);
    await page.getByRole('button', { name: 'Start chat', exact: true }).click();
    await page.locator('.nx-worktree-progress').waitFor({ timeout: 15000 });
    assert.match(await page.locator('.nx-worktree-progress').innerText(), /Preparing worktree|Checking out files|Finishing checkout/);
    await composer.fill(next);
    await page.waitForFunction(text => JSON.parse(localStorage.getItem('nx.draft.new') || 'null') === text, next);
    await page.screenshot({ path: 'scripts/evidence/DOGFIX-9-progress.png' });
    const job = await page.evaluate(() => JSON.parse(localStorage.getItem('nx.new.worktreeJob')));
    assert.ok(job.jobId);
    await page.reload();
    await page.getByRole('textbox', { name: 'First message' }).waitFor({ timeout: 45000 });
    assert.equal(await page.getByRole('textbox', { name: 'First message' }).inputValue(), next);
    assert.equal(await page.getByRole('textbox', { name: 'New branch name' }).inputValue(), branch);
    await page.waitForFunction(() => JSON.parse(localStorage.getItem('nx.new.worktreeJob') || 'null')?.status === 'completed', null, { timeout: 60000 });
    const ready = await page.evaluate(() => JSON.parse(localStorage.getItem('nx.new.worktreeJob')));
    assert.equal(ready.progress, 100);
    await page.getByRole('button', { name: 'Start chat', exact: true }).click();
    await page.waitForFunction(() => new URLSearchParams(location.search).has('chat'), null, { timeout: 45000 });
    await page.locator('.nx-msg-assistant').filter({ hasText: 'NEXT-DRAFT-DOGFIX' }).waitFor({ timeout: 60000 });
    // The thread also stays in its project after a fresh page load.
    const chat = new URL(page.url()).searchParams.get('chat');
    await page.reload();
    await page.locator('.nx-msg-assistant').filter({ hasText: 'NEXT-DRAFT-DOGFIX' }).waitFor({ timeout: 45000 });
    await page.getByRole('group', { name: fixture.name + '-' + branch, exact: true }).locator(`[data-session-id="${chat}"]`).waitFor({ timeout: 45000 }).catch(async error => {
      await page.screenshot({ path: '.agent_control/dogfix/sidebar-failure.png' });
      throw error;
    });
    await page.screenshot({ path: 'scripts/evidence/DOGFIX-9-ready.png' });
    await fs.writeFile('scripts/evidence/DOGFIX-worktree-rendered.json', JSON.stringify({ job, ready, chat, draftPreserved: true, sidebarAfterReload: true }, null, 2));
    console.log('Rendered progress, reload, draft and saved-project journeys passed');
  } else if ([7, 8].includes(bug)) {
    const saved = JSON.parse(await fs.readFile('.agent_control/dogfix/contracts/steered-session.json', 'utf8'));
    await page.goto('http://127.0.0.1:48902/control?chat=' + encodeURIComponent(saved.id));
    const composer = page.locator('form.nx-composer');
    await composer.locator('textarea').waitFor({ timeout: 45000 });
    await page.locator('.nx-msg-assistant').filter({ hasText: 'STEERED-DOGFIX' }).waitFor({ timeout: 45000 });
    if (bug === 8) {
      for (const width of [1440, 390]) {
        await page.setViewportSize({ width, height: 1000 });
        const geometry = await composer.evaluate(form => {
          const send = form.querySelector('.nx-send'), mic = form.querySelector('.nx-mic');
          const a = send.getBoundingClientRect(), b = mic.getBoundingClientRect();
          return { width: a.width, height: a.height, gap: a.left - b.right,
            rightEdgeIsSend: document.elementFromPoint(a.right - 2, a.top + a.height / 2)?.closest('button') === send,
            leftEdgeIsSend: document.elementFromPoint(a.left + 2, a.top + a.height / 2)?.closest('button') === send };
        });
        assert.ok(geometry.width >= 44 && geometry.height >= 44 && geometry.gap >= 16 && geometry.rightEdgeIsSend && geometry.leftEdgeIsSend, JSON.stringify(geometry));
        await page.screenshot({ path: `scripts/evidence/DOGFIX-8-${width}.png` });
      }
    } else {
      const prompt = `Verification ${Date.now()}. No file edits or agents. Run a PowerShell command that prints 50 in ANSI yellow: Write-Output ([char]27 + "[33m50" + [char]27 + "[39m"). Then reply ORDER-DOGFIX. No other commands.`;
      await composer.locator('textarea').fill(prompt);
      let microphoneRequests = 0;
      await page.evaluate(() => {
        window.dogfixMicRequests = 0;
        const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
        navigator.mediaDevices.getUserMedia = (...args) => { window.dogfixMicRequests++; return original(...args); };
      });
      const send = composer.locator('.nx-send');
      const previousTools = await page.locator('.nx-tool').count();
      await send.click({ position: { x: 3, y: 22 } });
      await page.waitForFunction(text => [...document.querySelectorAll('.nx-msg-user')].some(el => el.textContent.includes(text)), prompt.slice(0, 70), { timeout: 10000 });
      const order = await page.evaluate(text => {
        const items = [...document.querySelectorAll('.nx-msg-user,.nx-tool,.nx-msg-assistant')];
        const user = items.find(el => el.matches('.nx-msg-user') && el.querySelector('.nx-user-text')?.textContent === text);
        return { optimistic: user?.classList.contains('is-pending'), index: items.indexOf(user), total: items.length };
      }, prompt);
      assert.ok(order.index >= 0, JSON.stringify(order));
      await page.waitForFunction(count => document.querySelectorAll('.nx-tool').length > count, previousTools, { timeout: 60000 });
      const streamingOrder = await page.evaluate(text => {
        const user = [...document.querySelectorAll('.nx-msg-user')].find(el => el.querySelector('.nx-user-text')?.textContent === text);
        const tool = [...document.querySelectorAll('.nx-tool')].at(-1);
        return { userBeforeEffect: Boolean(user?.compareDocumentPosition(tool) & Node.DOCUMENT_POSITION_FOLLOWING) };
      }, prompt);
      assert.ok(streamingOrder.userBeforeEffect, JSON.stringify(streamingOrder));
      await page.waitForFunction(text => {
        const user = [...document.querySelectorAll('.nx-msg-user')].find(el => el.querySelector('.nx-user-text')?.textContent === text);
        return [...document.querySelectorAll('.nx-msg-assistant')].some(el => el.textContent.includes('ORDER-DOGFIX') && (user?.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING));
      }, prompt, { timeout: 60000 });
      const observed = await page.evaluate(text => {
        const items = [...document.querySelectorAll('.nx-msg-user,.nx-tool,.nx-msg-assistant')];
        const user = items.findIndex(el => el.matches('.nx-msg-user') && el.querySelector('.nx-user-text')?.textContent === text);
        const effect = items.findIndex((el, n) => n > user && el.matches('.nx-tool'));
        return { user, effect, microphoneRequests: window.dogfixMicRequests,
          output: [...document.querySelectorAll('.nx-tool-detail')].filter(e => e.querySelector('.nx-detail-label')?.textContent === 'Output').map(e => e.querySelector('pre')?.textContent).join('\n') };
      }, prompt);
      assert.ok(observed.user >= 0 && observed.effect > observed.user, JSON.stringify(observed));
      assert.equal(observed.microphoneRequests, 0);
      assert.ok(observed.output.includes('50') && !observed.output.includes('\x1b') && !observed.output.includes('[33m'), observed.output);
      await page.screenshot({ path: 'scripts/evidence/DOGFIX-7.png', fullPage: true });
      await fs.writeFile('scripts/evidence/DOGFIX-rendered.json', JSON.stringify({ order, streamingOrder, observed }, null, 2));
    }
    console.log(`Rendered DOGFIX-${bug} passed`);
    process.exitCode = 0;
  } else {
  await page.waitForSelector('.nx-folder-trigger', { timeout: 45000 });
  await page.getByRole('textbox', { name: 'First message' }).fill('Composer stays unchanged');
  await page.locator('.nx-folder-trigger').click();
  await page.waitForFunction(() => document.activeElement?.getAttribute('aria-label') === 'Search folders');
  await page.keyboard.type('new-folder-search');
  if (await page.getByRole('textbox', { name: 'First message' }).inputValue() !== 'Composer stays unchanged') throw new Error('Picker typed into the composer');
  if (await page.getByRole('textbox', { name: 'Search folders', exact: true }).inputValue() !== 'new-folder-search') throw new Error('Picker search lost focus');
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => document.activeElement?.classList.contains('nx-folder-trigger'));
  console.log((await page.locator('body').innerText()).slice(0, 6000));
  await page.screenshot({ path: 'scripts/evidence/DOGFIX-3.png' });
  }
} finally { await browser.close(); }
